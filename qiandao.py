import requests
import json
import os
import hashlib
import smtplib
import email
from apscheduler.schedulers.blocking import BlockingScheduler
import time

# 登录
def login():
    global headers
    global Token
    headers['Host'] = "apps.ulearning.cn"
    #用户名
    username = ""
    # 密码
    password = ""
    login_url = "https://apps.ulearning.cn/login"
    payload = {
        "loginName": username,
        "password": hashlib.md5(password.encode(encoding='UTF-8')).hexdigest(),
        # 手机型号
        "device": "",
        "appVersion":"36",
        "webEnv": "1"
    }
    response = requests.request(method='POST', url=login_url, headers=headers, data=json.dumps(payload))
    loginRes = response.json()
    if 'code' in loginRes:
        return login()
    else:
        with open('cookie.txt', 'wb', True) as f:
            f.write(json.dumps(loginRes).encode('UTF-8'))
            Token = loginRes
        headers['UA-AUTHORIZATION'] = loginRes['token']
        headers['Authorization'] = loginRes['token']
        return headers

# 主函数
def main(scheduler):
    global Token
    global headers
    headers = {
        'User-Agent': 'App ulearning Android',
        'Connection': 'close',
        'Accept-Language': 'CN',
        'uversion': "2",
        'Content-Type': 'application/json;charset=UTF-8'
    }
    try:
        f = open('cookie.txt')
        f.close()
    except FileNotFoundError:
        # 创建空白文件
        open('cookie.txt', 'w')
    except PermissionError:
        exit("You don't have permission to access this file")
    size = os.path.getsize('cookie.txt')
    with open('runlog.txt', 'w+') as f:
        f.write("the main func run in %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    if size == 0:
        print("开始登陆....")
        login()
    else:
        with open('cookie.txt', 'r') as f:
            s = f.read()
        Token = dict(json.loads(s))
        headers['UA-AUTHORIZATION'] = Token['token']
        headers['Authorization'] = Token['token']
    courses_list = get_courses_list()
    get_unaccomplished_homework(courses_list)
    # 定时任务首次运行则新建作业，次日运行就恢复休眠的作业
    if scheduler.get_job('get_attend') == None:
        scheduler.add_job(get_unattend_info, args=[courses_list, scheduler,], id='get_attend', trigger='interval',minutes=2)
    else:
        scheduler.resume_job('get_attend',jobstore=None)

    if scheduler.get_job('get_live') == None:
        scheduler.add_job(get_live_info, args=[courses_list,scheduler,], id='get_live', trigger='interval', hours=1)
    else:
        scheduler.resume_job('get_live',jobstore=None)

    if scheduler.get_job('get_discuss') == None:
        scheduler.add_job(get_discuss_info, args=[courses_list,scheduler,], id='get_discuss', trigger='interval', hours=1,minutes=30)
    else:
        scheduler.resume_job('get_discuss',jobstore=None)

# 获取所有课程
def get_courses_list():
    global headers
    headers['Host'] = "courseapi.ulearning.cn"
    get_courses_list_api = "https://courseapi.ulearning.cn/courses/students?publishStatus=-1&pn=1&ps=20&type=1"
    response = requests.request(method='GET', url=get_courses_list_api, headers=headers)
    if 'code' in response.json():
        with open('cookies.txt', 'wb', True) as f:
            f.truncate()
        print("身份已过期开始重新登陆")
        del headers['UA-AUTHORIZATION']
        del headers['Authorization']
        login()
        return get_courses_list()
    else:
        return response.json()['courseList']

#获取未完成的作业（每天一次）
def get_unaccomplished_homework(courses_list):
    global headers
    headers['Host'] = "courseapi.ulearning.cn"
    content = "你有来自\n"
    sendTip = False
    i = 0
    while i < len(courses_list):
        courses_name = courses_list[i]['name']
        get_homework_api = "https://courseapi.ulearning.cn/homeworks/student?ocId=%d&pn=1&ps=20" % courses_list[i]['id']
        response = requests.request(method='GET', url=get_homework_api, headers=headers)
        res = response.json()
        if 'homeworkList' in res and res['homeworkList']:
            j = 0
            while j<len(res['homeworkList']):
                if res['homeworkList'][j]['timeStatus'] == '2' and res['homeworkList'][j]['score'] == None and res['homeworkList'][j]['state'] == 0:
                    sendTip = True
                    content += res['homeworkList'][j]['publisher'] + "老师发布的" + courses_name + "课程，以" + res['homeworkList'][j]['homeworkTitle'] + "为题的作业\n"
                j += 1
        i += 1
    content += "等以上作业尚未完成，请及时完成"
    if sendTip:
        send_email(content, "优学院Python作业提醒脚本")

#获取课堂点名活动（每分钟检测一次）
def get_unattend_info(courses_list,scheduler):
    global headers
    global Token
    headers['Host'] = "courseapi.ulearning.cn"
    userId = Token['userID']
    status = False
    # 每次运行前检查时间，超时则停止
    if time.strftime("%H:%M:%S") >= "17:30:10":
        scheduler.pause_job('get_attend',jobstore=None)
    i = 0
    while i < len(courses_list):
        courses_name = courses_list[i]['name']
        classId = courses_list[i]['classId']
        get_homework_api = "https://courseapi.ulearning.cn/classActivity/stu/%d/-1?pn=1&ps=20" % courses_list[i]['id']
        response = requests.request(method='GET', url=get_homework_api, headers=headers)
        try:
            res = response.json()
        except:
            res = {
                'list': False
            }
        if 'list' in res and res['list']:
            j = 0
            while j < len(res['list']):
                if res['list'][j]['timeStatus'] == 2 and res['list'][j]['status'] != 1:
                    relationId = res['list'][j]['relationId']
                    startTime = res['list'][j]['startTime']
                    content = "%s课程发布了新的签到" % courses_name
                    status = post_attend(relationId, classId, userId)
                j += 1
        i += 1
    if status:
        send_email(content, "优学院自动签到提醒")

#获取课堂讨论每(90分钟检测一次)
def get_discuss_info(courses_list,scheduler):
    global headers
    headers['Host'] = "courseapi.ulearning.cn"
    sendTip = False
    if time.strftime("%H:%M:%S") >= "17:30:10":
        scheduler.pause_job('get_discuss',jobstore=None)
    i = 0
    while i < len(courses_list):
        courses_name = courses_list[i]['name']
        get_homework_api = "https://courseapi.ulearning.cn/forum/student/%d/-1?pn=1&ps=20 " % courses_list[i]['id']
        response = requests.request(method='GET', url=get_homework_api, headers=headers)
        res = response.json()
        if 'studentForumDiscussionList' in res and res['studentForumDiscussionList']:
            j = 0
            while j < len(res['studentForumDiscussionList']):
                if res['studentForumDiscussionList'][j]['state'] == 2 and res['studentForumDiscussionList'][j]['score'] == False:
                    discuss_title = res['studentForumDiscussionList'][j]['title']
                    sendTip = True
                    content = "你有来自%s课程的%s主题讨论还没参与。参与有积分哦！\n" % (courses_name, discuss_title)
                j += 1
        i += 1
    if sendTip:
        send_email(content, "优学院提醒参与讨论")

# 获取直播信息（每两个小时）
def get_live_info(courses_list,scheduler):
    global headers
    headers['Host'] = "courseapi.ulearning.cn"
    if time.strftime("%H:%M:%S") >= "17:30:10":
        scheduler.pause_job('get_live', jobstore=None)
    i = 0
    while i < len(courses_list):
        get_homework_api = "https://courseapi.ulearning.cn/livevideos/stu?pn=1&ps=20&ocId=%d" % courses_list[i]['id']
        response = requests.request(method='GET', url=get_homework_api, headers=headers)
        res = response.json()
        if 'list' in res and res['list']:
            j = 0
            while j < len(res['list']):
                if res['list'][j]['status'] == 2:
                    content = "%s老师开始%s主题直播了，赶紧参加直播" % (res['list'][j]['anchorName'],res['list'][j]['className'])
                    send_email(content, "优学院直播提醒")
                j += 1
        i += 1

#执行签到
def post_attend(attendanceID, classID, userId):
    global headers
    global geo
    headers['Host'] = "apps.ulearning.cn"
    if geo['lat'] == '' or geo['lon'] == '':
        ip2adress_api = "http://47.115.40.125:1234/getAddress.php"
        response1 = requests.request(method='GET', url=ip2adress_api)
        try:
            geo['lat'] = response1.json()['lat']
            geo['lon'] = response1.json()['lon']
        except OSError as e:
            exit(e)
    location = str(geo['lon']) + "," + str(geo['lat'])
    payload = {
        "attendanceID": attendanceID,
        "classID": classID,
        "userID": userId,
        "location": location,
        "enterWay":1,
        "attendanceCode":""
    }
    api = "https://apps.ulearning.cn/newAttendance/signByStu"
    response = requests.request(method='POST', url=api, data=json.dumps(payload), headers=headers)
    res = response.json()
    if 'status' in res and res['status'] == 200:
        return True
    else:
        return False


#发送邮件
def send_email(emailContent, emailSubject):
    global emailConfig
    conn = smtplib.SMTP_SSL('smtp.qq.com', 465)
    try:
        conn.login(emailConfig['FromAddr'], emailConfig['AuthorizationCode'])
    except OSError as e:
        exit(e)
    else:
        msg = email.message.EmailMessage()
        msg.set_content(emailContent)
        msg['subject'] = emailSubject
        msg['from'] = emailConfig['FromAddr']
        conn.sendmail(emailConfig['FromAddr'], emailConfig['ToAddr'], msg.as_string())
    finally:
        conn.close()

if __name__ == '__main__':
    global Token
    global headers
    global geo
    global emailConfig
    #坐标配置(服务器上运行需自行配置)
    geo = {
        'lat': '',
        'lon': '',
    }
    #邮件配置
    emailConfig = {
        'FromAddr': '',#发件人地址
        'AuthorizationCode': '',#发件邮箱授权码
        'ToAddr' : []#收件人地址
    }
    scheduler = BlockingScheduler()
    # 工作日早上八点运行
    scheduler.add_job(main, args=[scheduler,], id='main_job', day_of_week='mon-fri', trigger='cron', hour=8, minute=10)
    scheduler.start()