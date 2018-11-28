# coding=utf-8

# 导入蓝图对象api
from . import api
# 导入用户模型类
from ihome.models import User
# 导入request
from flask import request, jsonify, current_app, session, g
# 导入响应码
from ihome.utils.response_code import RET
# 导入用户验证登录装饰器
from ihome.utils.commons import login_required
# 导入图片上传的扩展包
from ihome.utils.image_storage import storage
# 导入配置的常量信息
from ihome import constants
# 导入数据库实例
from ihome import db
# 导入re模块
import re


# 用户登录模块
@api.route('/sessions',methods=['POST'])
def login():
    """
    用户登录
    前端post请求的get_json方法获取参数
    1.判断参数是否存在
    2.获取用户的mobile,password
    3.判断用户参数的完整性
    4.正则匹配用户的手机号码
    5.从数据库中查询用户信息，判断用户是否已经注册
    6.获取数据库中存储的用户密码
    7.比较用户输入密码和存储的密码是否一致
    8.如果一致，保存用户的登录状态
    9.返回结果
    :return:
    """
    # 获取参数
    user_data = request.get_json()
    # 参数是否存在
    if not user_data:
        return jsonify(errno=RET.PARAMERR,errmsg="参数获取失败")
    # 获取用户的mobile和password
    mobile = user_data.get("mobile")
    password = user_data.get("password")
    # 判断参数是否完整
    if not all([mobile,password]):
        return jsonify(errno=RET.PARAMERR,errmsg="参数不完整")
    # 用正则匹配手机号是否正确
    if not re.match(r'1[3456789]\d{9}',mobile):
        return jsonify(errno=RET.PARAMERR,errmsg="手机号格式不正确")
    # 从数据库中查询用户信息
    try:
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        # 记录log日志信息
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询用户信息异常")
    # 校验查询结果，并进行密码校验
    if user is None or not user.check_password(password):
        return jsonify(errno=RET.DATAERR,errmsg="用户名或密码错误")
    # session 缓存用户信息
    session['user_id'] = user.id
    session['name'] = user.name
    session['mobile'] = mobile
    # 返回结果
    return jsonify(errno=RET.OK,errmsg="OK",data={'user_id':user.id})


# 获取用户信息模块
@api.route('/user',methods=['GET'])
@login_required
def get_user_profile():
    """
    获取用户信息
    1.通过g变量获取用户的id
    2.查询数据库，确认用户是否存在
    3.校验查询结果
    4.返回结果
    :return:
    """
    # 获取用户的id
    user_id = g.user_id
    # 根据用户id查询数据库
    try:
        user = User.query.filter_by(id=user_id).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询用户信息异常")
    # 判断用户是否存在
    if not user:
        return jsonify(errno=RET.NODATA,errmsg="无效操作")
    # 返回用户的基本信息，调用模型类中的to_dict方法
    return jsonify(errno=RET.OK,errmsg="OK",data=user.to_dict())


# 上传用户头像模块
@api.route('/user/avatar',methods=['POST'])
@login_required
def set_user_avatar():
    """
    上传用户头像
    1.获取参数，用户选择上传的图片信息，request.files ,user_id=g.user_id
    2.校验参数是否存在
    3.读取图片数据read
    4.保存读取的图片数据，调用七牛云接口，上传图片
    5.保存调用七牛云接口后返回的图片名称，保存到数据库中
    6.提交数据，相对路径
    7.拼接图片的绝对路径
    8.返回结果
    :return:
    """
    # 获取用户的id
    user_id = g.user_id
    # 获取图片文件参数，avatar是表单页面的name字段，而不是ajax的data数据
    avatar = request.files.get("avatar")
    # 校验参数是否存在
    if not avatar:
        return jsonify(errno=RET.PARAMERR,errmsg="未上传图片")
    # 读取图片的数据
    avatar_data = avatar.read()
    # 调用七牛云接口，上传图片
    try:
        image_name = storage(avatar_data)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR,errmsg="上传七牛云失败")
    # 保存七牛云接口返回ide图片名字到数据库中
    try:
        User.query.filter_by(id=user_id).update({"avatar_url":image_name})
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        # 发生异常，进行数据库回滚
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="保存用户头像信息失败")
    # 返回前端图片的绝对路径
    image_url = constants.QINIU_DOMIN_PREFIX + image_name
    #返回结果
    return jsonify(errno=RET.OK,errmsg="OK",data={"avatar_url":image_url})


# 修改用户名模块
@api.route('/user/name',methods=['PUT'])
@login_required
def change_user_profile():
    """
    修改用户名
    1.获取参数，get_json()获取用户user_id,name
    2.校验参数，参数是否存在
    3.获取PUT请求参数里的name的值
    4.保存name信息到数据库中
    5.提交数据
    6.更新缓存的用户信息
    7.返回结果
    :return:
    """
    # 获取参数
    user_id = g.user_id
    user_data = request.get_json()
    # 校验参数
    if not user_data:
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    # 获取name的值
    name = user_data.get("name")
    if not name:
        return jsonify(errno=RET.PARAMERR,errmsg="用户名不能为空")
    # 保存name信息
    try:
        User.query.filter_by(id=user_id).update({"name": name})
        # 提交到数据库
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="更新用户名失败")
    # 跟新缓存的用户信息
    session['name'] = name
    # 返回结果
    return jsonify(errno=RET.OK,errmsg="OK",data={'name': name})


# 实名认证模块
@api.route('/user/auth',methods=['POST'])
@login_required
def set_user_auth():
    """
    用户实名认证模块
    1.获取参数，user_id
    2.通过post请求的get_json方法获取参数，real_name,id_card
    3.校验参数的完整性
    4.通过user_id查询数据库用户是否存在
    5.校验用户是否已经实名认证过
    6.保存用户的实名认证信息
    7.提交数据
    8.返回结果
    :return:
    """
    # 获取参数
    user_id = g.user_id
    user_data = request.get_json()
    # 判断参数是否存在
    if not user_data:
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    # 获取用户的真实名字和身份证号
    real_name = user_data.get("real_name")
    id_card = user_data.get("id_card")
    # 判断参数的完整性
    if not all([real_name, id_card]):
        return jsonify(errno=RET.PARAMERR,errmsg="参数不完整")
    # 查询数据库
    try:
        # 只有当姓名和身份证号都为空时才能完成更新操作
        User.query.filter_by(id=user_id,real_name=None,id_card=None).update({'real_name': real_name,'id_card': id_card})
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="保存用户实名信息失败")
    # 返回结果
    return jsonify(errno=RET.OK,errmsg="OK")


# 获取用户的实名信息
@api.route('/user/auth',methods=['GET'])
@login_required
def get_user_auth():
    """
    获取用户的实名信息
    1.获取参数，user_id
    2.根据user_id 查询数据库，保存查询结果
    3.校验查询结果
    4.返回结果
    :return:
    """
    # 获取参数
    user_id = g.user_id
    # 查询数据库
    try:
        user = User.query.filter_by(id=user_id).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询数据库错误")
    # 校验查询结果
    if not user:
        return jsonify(errno=RET.NODATA,errmsg="无效操作")
    # 返回结果
    return jsonify(errno=RET.OK,errmsg="OK",data=user.auth_to_dict())


# 用户退出模块
@api.route('/session',methods=['DELETE'])
@login_required
def logout():
    """
    用户退出模块
    1.查询用户的session信息
    2.删除用户的session信息
    3.返回结果
    :return:
    """
    # 在清除session信息前，先保存csrf_token
    csrf_token = session.get("csrf_token")
    # 使用请求上下文对象来清除用户的session信息
    session.clear()
    # 再次设置csrf_token
    session["csrf_token"] = csrf_token
    return jsonify(errno=RET.OK,errmsg="OK")


# 检查用户登录模块
@api.route('/session',methods=['GET'])
def check_user_login():
    """
    检查用户登录
    1.从session中获取用户信息，name,redis缓存
    2.判断获取结果，如果登录，返回name
    3.如果未登录，返回false
    :return:
    """
    # 获取用户的信息
    name = session.get("name")
    # 判断获取结果
    if name is not None:
        return jsonify(errno=RET.OK,errmsg="OK",data={'name':name})
    else:
        return jsonify(errno=RET.SESSIONERR,errmsg="false")
