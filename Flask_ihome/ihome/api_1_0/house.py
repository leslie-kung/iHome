# coding=utf-8

# 导入蓝图对象
from . import api
# 导入redis模块
from ihome import redis_store
# 导入flask内置的模块
from flask import current_app, jsonify, g, request, session
# 导入响应码模块
from ihome.utils.response_code import RET
# 导入地区模型类
from ihome.models import Area, House, Facility, HouseImage, User, Order
# 导入七牛云接口
from ihome.utils.image_storage import storage
# 导入常量配置信息
from ihome import constants, db
# 导入用户验证装饰器
from ihome.utils.commons import login_required
# 导入时间模块
import datetime

# 导入json
import json


# 城区信息模块
@api.route('/areas',methods=['GET'])
def get_areas_info():
    """
    获取城区参数，缓存--数据库---缓存
    1.读取缓存中的城区信息
    2.校验获取的结果，如果有直接返回
    3.如果没有，查询数据库中的城区数据
    4.校验查询结果
    5.定义容器存储查询结果
    6.遍历查询结果，需要调用模型类中的to_dict()方法
    7.把城区信息序列化
    8.把城区数据缓存到redis中
    9.返回结果
    :return:
    """
    # 从缓存中获取城区信息
    try:
        areas = redis_store.get("area_info")
    except Exception as e:
        current_app.logger.error(e)
        areas = None
    # 判断获取结果
    if areas:
        # 记录访问redis的历史
        current_app.logger.info("hit redis area info")
        resp =  '{"errno":0,"errmsg":"OK","data":%s}' % areas
        return resp
    # 如果缓存中没有数据，读取mysql中的数据
    try:
        areas = Area.query.all()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询数据库异常")
    # 判断查询结果
    if not areas:
        return jsonify(errno=RET.NODATA,errmsg="无城区信息")
    # 定义容器,存储查询结果
    areas_list = list()
    # 遍历查询结果集
    for area in areas:
        areas_list.append(area.to_dict())
    # 序列化城区信息
    areas_json = json.dumps(areas_list)
    # 缓存城区信息数据
    try:
        redis_store.setex("area_info",constants.AREA_INFO_REDIS_EXPIRES,areas_json)
    except Exception as e:
        current_app.logger.error(e)
    # 返回数据
    return '{"errno":0,"errmsg":"OK","data":%s}' % areas_json


# 发布新房源模块
@api.route('/houses',methods=['POST'])
@login_required
def save_house_info():
    """
    发布新房源
    1.获取参数,user_id,房屋的基本信息和配套设施，get_json
    2.校验参数的存在
    3.获取房屋的详细信息
    4.判断参数的完整性，不能包括facility字段
    5.对价格进行处理，前端一般用户输入都是以元为单位,为了确保数据的准确性,
    需要对价格转换,price = int ( float(price) * 100)
    6.构造模型类对象，准备存储数据
    7.尝试获取房屋的配套设施
    8.校验获取的房屋配套设施是否存在
    9.把房屋数据写入到数据库中
    10.返回结果
    :return:
    """
    # 获取参数user_id
    user_id = g.user_id
    house_data = request.get_json()
    # 判断参数是否存在
    if not house_data:
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    # 获取详细的房屋基本信息
    title = house_data.get('title')  # 房屋标题
    price = house_data.get('price')  # 房屋价格
    area_id = house_data.get("area_id")  # 房屋城区
    address = house_data.get('address')  # 房屋地址
    room_count = house_data.get('room_count')  # 房屋数目
    acreage = house_data.get('acreage')  # 房屋面积
    unit = house_data.get('unit')  # 房屋户型
    capacity = house_data.get('capacity')  # 适住人数
    beds = house_data.get('beds')  # 卧床配置
    deposit = house_data.get('deposit')  # 房屋押金
    min_days = house_data.get('min_days')  # 最小入住天数
    max_days = house_data.get('max_days')  # 最多入住天数
    # 校验参数的完整性
    if not all([title,price,area_id,address,room_count,acreage,unit,capacity,beds,deposit,min_days,max_days]):
        return jsonify(errno=RET.PARAMERR,errmsg="参数不完整")
    # 对价格进行处理
    try:
        price = int( float(price) * 100 )
        deposit = int( float(deposit) * 100 )
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DATAERR,errmsg="房屋价格数据错误")
    # 构造模型类，存储数据
    house = House()
    house.user_id = user_id
    house.area_id = area_id
    house.title = title
    house.price = price
    house.address = address
    house.room_count = room_count
    house.unit = unit
    house.capacity = capacity
    house.acreage = acreage
    house.beds = beds
    house.deposit = deposit
    house.min_days = min_days
    house.max_days = max_days
    # 尝试获取房屋的配套设施
    facility = house_data.get('facility')
    # 判断配套设施是否存在
    if facility:
        # 对配套设施进行检查，判断在数据库中是否存在
        try:
            facilities = Facility.query.filter(Facility.id.in_(facility)).all()
            # 存储房屋的配套设施
            house.facilities = facilities
        except Exception as e:
            current_app.logger.error(e)
            return jsonify(errno=RET.DBERR,errmsg="配套设施查询异常")
    # 存储房屋信息
    try:
        db.session.add(house)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="存储房屋信息失败")
    # 返回结果 返回的house_id是给后面上传房屋图片,和房屋进行关联
    return jsonify(errno=RET.OK,errmsg="OK",data={'house_id':house.id})


# 上传房屋图片信息
@api.route('/houses/<int:house_id>/images',methods=['POST'])
@login_required
def save_house_image(house_id):
    """
    上传房屋图片信息
    1.获取参数，用户上传的图片数据
    2.校验参数的存在
    3.根据house_id查询数据库，校验房屋的存在
    4.读取图片数据
    5.调用七牛云接口上传图片，保存返回的图片名字
    6.构造模型类对象HouseImage，存储图片关联的房屋
    7.临时提交图片数据到数据库
    8.查询用户房屋主图片是否设置
    9.如果没有设置，添加当期图片为主图片
    10.提交图片数据到数据库中commit
    11.拼接图片的url
    12.返回结果
    :param house_id:
    :return:
    """
    # 获取用户上传的图片
    image = request.files.get('house_image')
    # 检查参数是否存在
    if not image:
        return jsonify(errno=RET.PARAMERR,errmsg="图片未上传")
    # 查询房屋信息是否存在
    try:
        house = House.query.get(house_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询房屋信息异常")
    # 判断查询结果
    if not house:
        return jsonify(errno=RET.NODATA,errmsg="无房屋数据")
    # 读取图片数据
    image_data = image.read()
    # 调用七牛云接口，上传图片
    try:
        image_name = storage(image_data)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR,errmsg="图片上传失败")
    # 构造模型类HouseImage对象
    house_image = HouseImage()
    house_image.house_id = house_id
    house_image.url = image_name
    # 临时提交数据到house_image中
    db.session.add(house_image)
    # 判断房屋主图片是否设置，如未设置，进行设置
    if not house.index_image_url:
        house.index_image_url = image_name
        # 临时提交数据到会话对象当中
        db.session.add(house)
    # 提交数据到数据库中
    try:
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR,errmsg="保存图片数据失败")
    # 拼接图片的url（绝对路径）
    image_url = constants.QINIU_DOMIN_PREFIX + image_name
    # 返回结果
    return jsonify(errno=RET.OK,errmsg="OK",data={'url':image_url})


# 我的房源信息模块
@api.route('/user/houses',methods=['GET'])
@login_required
def get_myhouse_info():
    """
    查询我的房源信息模块
    1.获取用户的id
    2.查询数据库，user_id
    3.定义容器
    4.判断查询结果，如果有数据，保存到容器中，遍历
    5.返回结果
    :return:
    """
    # 获取用户id
    user_id = g.user_id
    # 判断用户是否进行过实名认证
    try:
        user = User.query.get(user_id)
        real_name = user.real_name
        # id_card = User.query.filter_by("id_card").first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询数据库异常")
    # 判断查询结果
    if not real_name:
        return jsonify(errno=RET.NODATA,errmsg="用户未认证")
    # 从数据库中获取房源信息
    try:
        user = User.query.get(user_id)
        # 使用反向引用
        houses = user.houses
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询用户房屋数据异常")
    # 定义容器
    house_list = list()
    if houses:
        for house in houses:
            house_list.append(house.to_basic_dict())
    # 返回结果
    return jsonify(errno=RET.OK,errmsg="OK",data={'houses':house_list})


# 项目首页幻灯片模块
@api.route('/houses/index',methods=['GET'])
def get_house_index():
    """
    项目首页幻灯片
    1.尝试从缓存中获取房屋图片数据，缓存---数据库---缓存
    2.如果有数据，留下访问redis的记录
    3.返回redis中存储的图片数据
    4.如果没有，从数据库中获取
    5.对幻灯片的处理，默认是房屋成交次数，最多展示5条
    6.判断获取结果
    7.定义容器，遍历获取结果，判断房屋是否设置图片，如未设置，默认不添加
    8.序列化房屋数据
    9.保存到redis缓存中
    10.返回结果
    :return:
    """
    # 尝试从缓存中获取数据
    try:
        ret = redis_store.get('home_page_data')
    except Exception as e:
        current_app.logger.error(e)
        ret = None
    # 判断获取结果，如果有数据，留下访问记录，直接返回结果
    if ret:
        current_app.logger.info('hit redis get home_page_data')
        resp = '{"errno":0,"errmsg":"OK","data":%s}' % ret
        return resp

    # 查询数据库，默认按房屋成交数量进行排序
    try:
        houses = House.query.order_by(House.order_count.desc()).limit(constants.HOME_PAGE_MAX_HOUSES)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询房屋数据异常")
    # 判断查询结果
    if not houses:
        return jsonify(errno=RET.NODATA,errmsg="无房屋数据")
    # 定义容器，存储查询结果
    houses_list = list()
    # 遍历查询结果，过滤没有房屋主图片的房屋数据
    for house in houses:
        if not house.index_image_url:
            continue
        houses_list.append(house.to_basic_dict())
    # 序列化房屋数据
    house_json = json.dumps(houses_list)
    # 保存到redis缓存中
    try:
        redis_store.setex("home_page_data",constants.HOME_PAGE_DATA_REDIS_EXPIRES,house_json)
    except Exception as e:
        current_app.logger.error(e)
    # 构造响应结果返回结果
    resp = '{"errno":0,"errmsg":"OK","data":%s}' % house_json
    return resp


# 获取房屋详情模块
@api.route('/houses/<int:house_id>',methods=['GET'])
def get_house_detail(house_id):
    """
    获取房屋详情信息
    1.尝试获取用户的身份 user_id
    2.校验house_id 参数的存在
    3.尝试从redis中获取房屋的详情信息
    4.校验查询结果
    5.从数据库中获取房屋的详细数据
    6.校验查询结果，确认房屋存在
    7.调用模型类中的house.to_full_dict()
    8.序列化数据
    9.保存到redis缓存中
    10.构造响应数据
    11.返回结果
    :param house_id:
    :return:
    """
    # 获取用户的id
    user_id = session.get("user_id","-1")
    # 确认参数house_id的存在
    if not house_id:
        return jsonify(errno=RET.PARAMERR,errmsg="参数错误")
    # 尝试从redis中获取房屋的信息
    try:
        ret = redis_store.get("house_info_%s" % house_id)
    except Exception as e:
        current_app.logger.error(e)
        ret = None
    # 判断查询结果
    if ret:
        current_app.logger.info("hit redis house_detail_info")
        resp = '{"errno":0,"errmsg":"OK","data":{"user_id":%s,"house":%s}}' % (user_id,ret)
        return resp

    # 查询数据库，获取房屋信息
    try:
        house = House.query.get(house_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询房屋数据异常")
    # 判断查询结果
    if not house:
        return jsonify(errno=RET.NODATA,errmsg="房屋不存在")

    # 调用模型类，获取房屋详情数据
    try:
        # 因为to_full_dict方法里面实现房屋详情数据,需要查询数据库,所以进行异常处理
        house_data = house.to_full_dict()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询房屋详情数据异常")
    # 序列化详情数据
    house_json = json.dumps(house_data)
    # 保存到缓存中
    try:
        redis_store.setex('house_info_%s' % house_id,constants.HOUSE_DETAIL_REDIS_EXPIRE_SECOND,house_json)
    except Exception as e:
        current_app.logger.error(e)
    # 构造响应结果，返回结果
    resp = '{"errno":0,"errmsg":"OK","data":{"user_id":%s,"house":%s}}' % (user_id,house_json)
    return resp


# 房屋列表页模块
@api.route('/houses',methods=['GET'])
def get_houses_list():
    """
    获取房屋列表页
    缓存----磁盘----缓存
    业务逻辑：获取参数，校验参数，业务处理，返回结果
    目的：根据用户选择的参数信息，把符合要求的房屋数据返回给用户
    1.获取参数：sd,ed,aid,sk,p
    2.对日期进行格式化处理
    3.开始日期必须小于等于结束日期
    4.对页数进行格式化处理
    5.尝试从redis中获取房屋的列表信息，使用哈希数据类型
    6.判断获取结果，如果有数据，留下访问记录，直接返回
    7.查询mysql数据库
    8.定义容器列表，存储用户选择的条件参数（查询的过滤条件）
    9.判断区域参数是否存在，如果存在，添加到列表中
    10.判断日期参数是否存在，将得到的日期和数据库中订单的日期进行比较，返回满足条件的房屋信息
    11.判断排序条件，根据排序条件执行查询数据库的操作
    12.根据排序结果进行分页处理，paginate返回结果包括总页数和房屋数据
    13.遍历房屋数据，调用模型类中的方法，获取房屋的基本信息
    14.构造响应报文
    15.序列化数据
    16.将房屋数据写入到缓存中（判断用户选择的页数小于分页的总页数，本质上是用户选择的页数是有数据的）
    17.构造redis_key,存储房屋列表页的缓存数据，,因为使用的是hash数据类型,为了确保数据的完整性,需要使用事务;开启事务,存储数据,设置有效期,执行事务/
    pip = redis_store.pipeline()
    18.返回结果resp_json
    :return:
    """
    # 获取参数，area_id,start_date_str,end_date_str,sort_key,page
    area_id = request.args.get('aid','')
    start_date_str = request.args.get('sd','')
    end_date_str = request.args.get('ed','')
    sort_key = request.args.get('sk','new')
    page = request.args.get('p',1)
    # 参数处理,对日期进行处理
    try:
        # 保存格式化后的日期
        start_date,end_date = None,None
        # 判断开始日期的存在
        if start_date_str:
            start_date = datetime.datetime.strptime(start_date_str,'%Y-%m-%d')
        # 判断离开日期的存在
        if end_date_str:
            end_date = datetime.datetime.strptime(end_date_str,'%Y-%m-%d')
        # 如果开始日期和结束日期都存在，需要确认用户选择的至少有一天
        if start_date_str and end_date_str:
            assert start_date_str <= end_date_str
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR,errmsg="日期格式化错误")
    # 对页数进行格式化
    try:
        page = int(page)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR,errmsg="页数格式化错误")
    # 尝试从redis缓存中获取房屋的列表数据,因为多条数据的存储,使用的hash数据类型,首先需要键值
    try:
        # redis_key相当于hash的对象，里面存储的是页数和房屋数据
        redis_key = 'houses_%s_%s_%s_%s' % (area_id, start_date_str, end_date_str, sort_key)
        # 根据redis_key 获取缓存数据
        ret = redis_store.hget(redis_key,page)
    except Exception as e:
        current_app.logger.error(e)
        ret = None
    # 判断获取结果,如果有数据，留下记录返回结果
    if ret:
        current_app.logger.info('hit redis houses_list_info')
        # ret里面已经是完整的响应报文,所以可以直接返回
        return ret
    # 查询磁盘数据库，过滤条件---查询数据库---排序---分页，得到满足条件的房屋
    try:
        # 定义容器，存储过滤条件
        params_filter = list()
        # 判断区域的存在
        if area_id:
            # 列表中添加的是sqlalchemy对象
            params_filter.append(House.area_id == area_id)
        # 对日期参数进行查询，如果用户选择了开始和结束日期
        if start_date and end_date:
            # 存储有冲突的订单
            conflict_orders = Order.query.filter(Order.begin_date<=end_date,Order.end_date>=start_date).all()
            # 遍历有冲突的订单，获取有冲突的房屋
            conflict_house_id = [order.house_id for order in conflict_orders]
            # 判断有冲突的房屋的存在，取反获取没有冲突的房屋
            if conflict_house_id:
                params_filter.append(House.id.notin_(conflict_house_id))
        # 如果用户只选择了开始日期
        elif start_date:
            conflict_orders = Order.query.filter(Order.end_date>=start_date).all()
            conflict_house_id = [order.house_id for order in conflict_orders]
            if conflict_house_id:
                params_filter.append(House.id.notin_(conflict_house_id))
        # 如果用户只选择了结束日期
        elif end_date:
            conflict_orders = Order.query.filter(Order.begin_date <= end_date).all()
            conflict_house_id = [order.house_id for order in conflict_orders]
            if conflict_house_id:
                params_filter.append(House.id.notin_(conflict_house_id))
        # 过滤条件实现后，执行查询排序操作
        # 按成交次数排序
        if 'booking' == sort_key:
            houses = House.query.filter(*params_filter).order_by(House.order_count.desc())
        # 按价格升序排序
        elif 'price-inc' == sort_key:
            houses = House.query.filter(*params_filter).order_by(House.price.asc())
        # 按价格降序排序
        elif 'price-des' == sort_key:
            houses = House.query.filter(*params_filter).order_by(House.price.desc())
        # 默认排序方式 房屋发布时间最新
        else:
            houses = House.query.filter(*params_filter).order_by(House.create_time.desc())

        # 对排序结果进行分页操作False表示分页异常不报错
        house_page = houses.paginate(page,constants.HOUSE_LIST_PAGE_CAPACITY,False)
        # 获取分页后房屋数据和总页数
        house_list = house_page.items
        total_page = house_page.pages
        # 定义容器，遍历分页后的房屋数据，调用模型类中的方法，获取房屋的基本信息
        houses_dict_list = []
        for house in house_list:
            houses_dict_list.append(house.to_basic_dict())
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg="查询房屋列表信息异常")
    # 构造响应报文
    resp = {"errno":0,"errmsg":"OK","data":{"houses":houses_dict_list,"total_page":total_page,"current_page":page}}
    # 序列化数据
    resp_json = json.dumps(resp)
    # 存储序列化的房屋数据列表
    # 判断用户请求的页数小于总页数，即用户请求的页数有数据
    if page <= total_page:
        redis_key = 'houses_%s_%s_%s_%s' % (area_id, start_date_str, end_date_str, sort_key)
        # 使用事务对多条数据同时进行操作
        pip = redis_store.pipeline()
        try:
            # 开启事务
            pip.multi()
            # 存储数据
            pip.hset(redis_key,page,resp_json)
            # 设置过期时间
            pip.expire(redis_key,constants.HOUSE_LIST_REDIS_EXPIRES)
            # 执行事务
            pip.execute()
        except Exception as e:
            current_app.logger.error(e)
    # 返回响应数据
    return resp_json
