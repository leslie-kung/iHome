# coding=utf-8

# 导入蓝图
from . import api
# 导入flask的内置模块
from flask import request,g,jsonify,current_app
# 导入用户登录验证模块
from ihome.utils.commons import login_required
# 导入自定义响应码
from ihome.utils.response_code import RET
# 导入模型类对象
from ihome.models import House,Order
# 导入数据库对象
from ihome import db,redis_store
# 导入时间模块
import datetime


# 保存订单信息模块
@api.route('/orders',methods=['POST'])
@login_required
def save_orders():
    """订单保存"""
    user_id = g.user_id
    # 获取参数
    order_data = request.get_json()
    if not order_data:
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    # 进一步获取参数的详细信息
    house_id = order_data.get("house_id")
    start_date_str = order_data.get("start_date")
    end_date_str = order_data.get("end_date")

    # 参数完整性检查
    if not all([house_id,start_date_str,end_date_str]):
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    # 日期格式检查
    try:
        # 将请求的时间参数字符串转化为datetime类型
        start_date = datetime.datetime.strptime(start_date_str,"%Y-%m-%d")
        end_date = datetime.datetime.strptime(end_date_str,"%Y-%m-%d")
        assert start_date <= end_date
        # 计算预定的天数
        days = (end_date - start_date).days + 1
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR,errmsg="日期格式错误")
    # 查询房屋是否存在
    try:
        house = House.query.get(house_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="获取房屋信息失败")
    # 判断查询结果
    if not house:
        return jsonify(errno=RET.NODATA,errmsg="无房屋数据信息")
    # 预定的房屋是否是房东自己的
    if user_id == house.user_id:
        return jsonify(errno=RET.ROLEERR,errmsg="不能预定自己的房间")
    # 确保用户预定的时间内，房屋没有被比人下单
    try:
        # 查询时间冲突的订单数
        count = Order.query.filter(Order.house_id == house_id,
                                   Order.begin_date <= end_date,
                                   Order.end_date >= start_date).count()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="检查出错，稍后再试")
    if count > 0:
        return jsonify(errno=RET.DATAERR,errmsg="房屋已经被预定")
    # 订单总额
    amount = days*house.price
    # 保存订单数据
    order = Order()
    order.house_id = house_id
    order.user_id = user_id
    order.begin_date = start_date
    order.end_date =end_date
    order.days = days
    order.house_price = house.price
    order.amount = amount
    # 保存到数据库中
    try:
        db.session.add(order)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        # 操作错误，进行回滚
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="保存数据失败")
    return jsonify(errno=RET.OK,errmsg="OK",data={"order_id":order.id})


# 查询用户订单信息模块
@api.route('/user/orders',methods=['GET'])
@login_required
def get_user_orders():
    """查询用户订单信息模块"""
    user_id = g.user_id
    # 用户的身份，是客户还是房东
    role = request.args.get('role','')
    # 查询订单数据
    try:
        if 'landlord' == role:
            # 以房东的身份进行查询
            # 先查询属于自己的房屋有哪些
            houses = House.query.filter(House.user_id == user_id).all()
            houses_ids = [houses.id for house in houses]
            # 在查询预定了自己房屋的有哪些
            orders = Order.query.filter(Order.house_id.in_(houses_ids)).order_by(Order.create_time.desc()).all()
        else:
            # 以房客的身份进行查询，查看自己预定的房屋订单
            orders = Order.query.filter(Order.user_id == user_id).order_by(Order.create_time.desc()).all()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询订单信息失败")
    # 定义容器 将订单对象转换未字典数据
    orders_dict_list = []
    if orders:
        for order in orders:
            orders_dict_list.append(order.to_dict())
    return jsonify(errno=RET.OK,errmsg='OK',data={"orders":orders_dict_list})


# 接单拒单模块
@api.route('/orders/<int:order_id>/status',methods=["PUT"])
@login_required
def accept_reject_order(order_id):
    """接单、拒单模块"""
    user_id = g.user_id
    # 获取参数
    req_data = request.get_json()
    if not req_data:
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    # action参数表明客户端请求是接单还是拒单的行为
    action = req_data.get("action")
    if action not in ("accept","reject"):
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    try:
        # 根据订单号查询订单，并且要求订单处于待接单的状态
        order = Order.query.filter(Order.id == order_id,Order.status == "WAIT_ACCEPT").first()
        house = order.house
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="无法获取订单数据")
    # 确保房东只能修改属于自己的房屋订单
    if not order or house.user_id != user_id:
        return jsonify(errno=RET.REQERR,errmsg="无效操作")
    if action == "accept":
        # 接单，讲订单状态设为等待评论
        order.status = "WAIT_COMMENT"
    elif action == "reject":
        # 拒单，要去拒单原因
        reason = req_data.get("reason")
        if not reason:
            return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
        order.status = "REJECTED"
        order.comment = reason
    try:
        db.session.add(order)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="操作失败")
    return jsonify(errno=RET.OK,errmsg="OK")


# 保存订单评论信息模块
@api.route('/orders/<int:order_id>/comment',methods=['PUT'])
@login_required
def save_order_comment(order_id):
    """保存订单评论信息"""
    user_id = g.user_id
    # 获取参数
    req_data = request.get_json()
    comment = req_data.get("comment")
    # 检查参数
    if not comment:
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    try:
        # 需要确保只能评论自己下的单，而且订单是处于待评论状态
        order = Order.query.filter(Order.id==order_id,Order.user_id==user_id,
                                   Order.status=="WAIT_COMMENT").first()
        house = order.house
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="无法获取订单数据")
    if not order:
        return jsonify(errno=RET.REQERR,errmsg="无效操作")
    try:
        # 将订单的状态设置为已完成
        order.status = "COMPLETE"
        # 保存订单的评价信息
        order.comment = comment
        # 将房屋的完成订单数增1
        house.order_count += 1
        db.session.add(order)
        db.session.add(house)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="操作失败")
    # 因房屋的详情中有订单评价信息，为了让最新的评价信息展示在房屋详情中，所以删除redis中本订单的缓存
    try:
        redis_store.delete("house_info_%s" % order.house.id)
    except Exception as e:
        current_app.logger.error(e)

    return jsonify(errno=RET.OK,errmsg="OK")
