# coding=utf-8

# 导入蓝图对象api
from . import api
# 从captcha扩展包中导入captcha
from ihome.utils.captcha.captcha import captcha
# 导入redis数据库
from ihome import redis_store,constants,db
# 导入current_app
from flask import current_app,jsonify,make_response,request,session
# 导入自定义状态码
from ihome.utils.response_code import RET
# 导入用户信息模块
from ihome.models import User
# 导入云通讯扩展包
from ihome.utils import sms
# 导入正则re
import re
import random

@api.route("/imagecode/<image_code_id>", methods=['GET'])
def generate_image_code(image_code_id):
    """
    生成图片验证码
    1.导入使用captcha包扩展包，生成图片验证码，name,text,image
    2.在服务器中保存图片验证码，保存到redis中，
    3.如果保存失败，返回错误信息，保存到日志中
    4.返回图片，使用make_response对象
    :param image_code_id:
    :return:
    """
    # 生成图片验证码
    name,text,image = captcha.generate_captcha()
    # 保存图片验证码到redis中
    try:
        redis_store.setex('ImageCode_' + image_code_id, constants.IMAGE_CODE_REDIS_EXPIRES, text)
    except Exception as e:
        # 记录错误日志信息
        current_app.logger.error(e)
        # 返回错误结果
        return jsonify(errno=RET.DBERR,errmsg="保存图片验证码失败")
    # 如果未发生错误执行else
    else:
        # 使用响应对象响应图片
        response = make_response(image)
        # 返回结果
        return response


@api.route('/smscode/<mobile>', methods=['GET'])
def send_sms_code(mobile):
    """
    发送短信：获取参数-校验参数-查询数据（业务处理）-返回结果
    1.获取参数，mobile,text,id(验证码编号)
    2.校验参数完整性，正则匹配手机号
    3.从本地中获取存储的图片验证码
    4.判断获取结果是否存在
    5.删除缓存中已经读取过的图片验证码，只能读取一次
    6.比较两次的验证码是否一致
    7.发送短信，云通讯只能提供网络服务，内容需要自定(随机数)
    8.生成一个短信验证码，六位的随机数
    9.存数生成的验证码到redis中
    10.准备发送短信，判断用户是否依据能够注册，
    11.保存发送结果，判断是否发送成功
    12.返回结果
    :param mobile:
    :return:
    """
    # 获取参数text为图片验证码的内容，id为图片验证码的编号
    image_code = request.args.get('text')
    image_code_id = request.args.get('id')

    # 校验参数的完整性
    if not all([mobile,image_code,image_code_id]):
        return jsonify(errno=RET.PARAMERR,errmsg="参数不完整")

    # 正则匹配手机号码是否正确
    if not re.match(r"1[3456789]\d{9}", mobile):
        return jsonify(errno=RET.PARAMERR,errmsg="手机号格式错误")

    # 从本地中获取存储的图片验证码
    try:
        real_image_code = redis_store.get('ImageCode_' + image_code_id)
    except Exception as e:
        # 记录current_app日志中
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="获取图片验证码失败")

    # 判断验证码是否存在
    if not real_image_code:
        return jsonify(errno=RET.PARAMERR,errmsg="验证码不存在")

    # 删除redis保存的已经读取过的验证码
    try:
        redis_store.delete("ImageCode_" + image_code_id)
    except Exception as e:
        current_app.logger.error(e)

    # 判断两次的验证码是否一致，忽略大小写
    if image_code.lower() != real_image_code.lower():
        return jsonify(errno=RET.DATAERR,errmsg="图片验证码不一致")

    # 生成验证码随机数
    sms_code = "%06d" % random.randint(1,999999)

    # 保存验证码到redis中
    try:
        redis_store.setex("SMSCode_" + mobile, constants.SMS_CODE_REDIS_EXPIRES, sms_code)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="验证码保存失败")

    # 判断用户是否已经注册
    try:
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询数据库失败")

    # 判断用户查询结果
    if user:
        return jsonify(errno=RET.DATAEXIST,errmsg="手机号已经注册")

    # 调用云通讯发送验证码短信
    try:
        send_sms = sms.CCP()
        result = send_sms.send_template_sms(mobile,[sms_code,constants.SMS_CODE_REDIS_EXPIRES/60],1)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR,errmsg="发送短信失败")

    # 判断返回结果，
    if 0 == result:
        return jsonify(errno=RET.OK,errmsg="发送成功")
    else:
        return jsonify(errno=RET.THIRDERR,errmsg="发送失败")


@api.route('/users',methods=['POST'])
def register():
    """
    request的get_json()方法获取前端post发送过来的data数据
    1.获取参数mobile,sms_code,password
    2.校验参数，判断参数是否完整
    3.正则匹配手机号
    4.查询redis中存储的短信验证码
    5.判断短信验证码是否一致
    6.如果一致删除短信验证码
    7.构造模型类，存储用户信息
    8.提交数据到数据库中
    9.缓存用户的session信息
    10.返回结果
    :return:
    """
    user_data = request.get_json()
    # 校验参数的存在
    if not user_data:
        return jsonify(errno=RET.PARAMERR,errmsg="参数获取失败")

    # 获取参数的详细信息
    mobile = user_data.get("mobile")
    sms_code = user_data.get("sms_code")
    password = user_data.get("password")

    # 校验参数的完整性
    if not all([mobile,sms_code,password]):
        return jsonify(errno=RET.PARAMERR,errmsg="参数不完整")

    # 判断手机号是否正确
    if not re.match(r'1[3456789]\d{9}',mobile):
        return jsonify(errno=RET.PARAMERR,errmsg="手机号格式不正确")

    # 判断手机号是否已经注册
    try:
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="数据查询失败")
    else:
        if user:
            return jsonify(errno=RET.DATAEXIST,errmsg="用户已经注册")

    # 查询redis中存储的验证码信息
    try:
        real_sms_code = redis_store.get("SMSCode_" + mobile)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR,errmsg="获取本地验证码失败")

    # 判断获取的结果
    if not real_sms_code:
        return jsonify(errno=RET.PARAMERR,errmsg="本地验证码不存在")

    # 判断用户输入的验证码和本地验证码是否一致
    if real_sms_code != str(sms_code):
        return jsonify(errno=RET.DATAERR,errmsg="验证码不一致")

    # 删除短信验证码
    try:
        redis_store.delete("SMSCode_" + mobile)
    except Exception as e:
        current_app.logger.error(e)

    # 使用User模型类，存储用户信息
    user = User(mobile=mobile, name=mobile)
    # 调用模型类的password方法，实现密码加密
    user.password = password

    # 保存数据到数据库中
    try:
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        # 发生异常，进行回滚
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="数据保存失败")

    # 缓存用户信息
    session['user_id'] = user.id
    session['name'] = mobile
    session['mobile'] = mobile

    # 返回结果
    return jsonify(errno=RET.OK,errmsg="保存数据成功",data=user.to_dict())
