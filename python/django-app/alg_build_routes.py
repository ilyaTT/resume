# -*- coding: utf-8 -*-

import datetime
import logging
import traceback
from collections import OrderedDict
from collections import deque, defaultdict
from itertools import chain
from django.utils.timezone import make_aware
from distance import OsrmDistance, MODE_FULL
from asuothodi.alg_traveling import AlgTraveling
from asuothodi.models import ContainerPlatform, Landfill, Depot, PlatformRestrict


LOG = logging.getLogger(__name__)


def toPoint(obj):
    return obj.__dict__

def toStr(p):
    # вернет строковое представление координат точки
    return '%s,%s' % (float(p['lat']), float(p['lon']))


class Target(object):

    time_step_keys = {
        'to_prev_landfill': u'до предварительной выгрузки',
        'work_prev_landfill': u'работа на предварительной выгрузке',
        'to_cont': u'до контейнера',
        'work_cont': u'работа на контейнере',
        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################
    }

    cost_step_keys = {
        'work_start': u'выход на рейс',
        'capacity': u'по объему',
        'hours': u'по часам',
        'km': u'по км',
    }

    # веса стоимости и времени. определяют удельный вес направления оптимизации
    weight_time = 1
    weight_cost = 1

    def __init__(self, cont, car):
        # входные параметры
        self.car = car
        self.cont = cont

        # результат расчета
        self.time = 0
        self.km = 0
        self.cost = 0
        self.reject = None

        # шаги расчета
        self.time_steps = OrderedDict()
        self.km_steps = OrderedDict()
        self.cost_steps = OrderedDict()

        try:
            # проверяем, может ли машина забрать данный тип
            if cont.type.id not in car.container_types:
                raise CarReject(u'Не подходит тип контейнера: %s' % cont.type.name)

            # проверяем, покрывает ли машина все ограничения площадки
            restricts = set(cont.platform.restricts.values_list('id', flat=True)) - car.platform_restricts
            if restricts:
                raise CarReject(u'Не подходит ограничение площадки: %s' % ','.join(
                    PlatformRestrict.objects.filter(id__in=restricts).values_list('name', flat=True)))

            # выполняем расчеты
            self.calcTime()
            self.calcCost()

        except CarReject as e:
            self.reject = unicode(e)
        except Exception:
            print 'Exception car:', car.t.__dict__
            raise

    def calcTime(self):
        # сокращения
        car = self.car
        cont = self.cont
        cont_capacity = cont.capacity or cont.type.capacity

        # если контейнер не съемный
        if not cont.type.is_portable:
            # вычисляем новую остаточную массу и объем
            capacity_left = car.capacity_left - cont_capacity
            carrying_capacity_left = car.carrying_capacity_left - (cont_capacity * Car.DENSITY)

            # если не влазим - везем через выгрузку
            if capacity_left < 0 or carrying_capacity_left < 0:
                # время от контейнера до выгрузкок в сек
                time_to_landfills = [car.distSecond(car.dist(car.now_point, u)) for u in car.landfills]
                # берем самую ближ.
                time_to_landfill = min(time_to_landfills)
                landfill = car.landfills[time_to_landfills.index(time_to_landfill)]

                self.time_steps['to_prev_landfill'] = time_to_landfill
                self.km_steps['to_prev_landfill'] = car.dist(car.now_point, landfill)

                # время на выгрузке в сек
                self.time_steps['work_prev_landfill'] = landfill.work_time

                # от выгрузки до контейнера
                self.km_steps['to_cont'] = car.dist(landfill, cont.platform)
                self.time_steps['to_cont'] = car.distSecond(self.km_steps['to_cont'])

        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################

        self.time_steps['to_depot'] = car.distSecond(self.km_steps['to_depot'])

        # совокупное время на обработку контейнера
        self.time = sum(self.time_steps.values())

        # совокупное расстояние на обработку контейнера
        self.km = sum(self.km_steps.values())

        # проверяем, если машина поедет за этим контейнером - не произойдет ли превышения переработки
        if car.left_time - self.time < -car.left_overtime:
            raise CarReject(u'Превышение переработки на %s сек' % (self.time - (car.left_time + car.left_overtime)))

    def calcCost(self):
        # результат вычисления - заполненный cost
        self.cost = 0

        # сокращения
        car = self.car
        cont = self.cont
        cont_capacity = cont.capacity or cont.type.capacity

        # если находимся на базе - добавляем стоимость выхода машины на рейс
        if isinstance(car.now_point, Depot):
            self.cost_steps['work_start'] = 3000

        # стоимость обработки контейнера по объему
        self.cost_steps['capacity'] = cont_capacity * car.cost_capacity
        # стоимость обработки контейнера по часам
        self.cost_steps['hours'] = (self.time / 3600.0) * car.cost_work
        # стоимость обработки контейнера по км
        self.cost_steps['km'] = self.km * car.cost_dist

        # совокупная стоимость шагов
        cost_steps = sum(self.cost_steps.values())

        # проверяем, будет ли переработка на этом шаге
        if car.left_time - self.time < 0:
            # определяем долю стоимости, которая придется на переработку
            overtime_rate = (self.time - car.left_time) / self.time
            # увеличиваем стоимость
            cost_steps += (cost_steps * overtime_rate) * car.overtime_coef

        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################


    def __unicode__(self):
        # вычисляем результат функции
        if self.reject:
            result = u'Не участвует: %s' % self.reject
        else:
            result = u'Стоимость: %s. Время: %s' % (self.cost, self.time)

        # шаги расчета времени
        if self.time_steps:
            time_steps = u'\n\tШаги расчета времени работы:'
            time_steps += ''.join(['\n\t\t - %s: %s' % (self.time_step_keys[k], v) for k, v in self.time_steps.items()])
        else:
            time_steps = ''

        # шаги расчета стоимости
        if self.cost_steps:
            cost_steps = u'\n\tШаги расчета стоимости работы:'
            cost_steps += ''.join(['\n\t\t - %s: %s' % (self.cost_step_keys[k], v) for k, v in self.cost_steps.items()])
        else:
            cost_steps = ''

        # информация о текущем местоположении
        return u'%s. %s. %s\n%s' % (
            unicode(self.car),
            result,
            time_steps,
            cost_steps
        )

    __repr__ = __unicode__

    @staticmethod
    def sort(targets):

        if not targets:
            return

        # списки времени и стоимости
        times = [t.time for t in targets]
        costs = [t.cost for t in targets]

        # средние времени и стоимости
        avg_times = 1.0 * sum(times) / len(times)
        avg_costs = 1.0 * sum(costs) / len(costs)

        # функция сравнения
        def compare(t1, t2):
            # убираем все отклоненные цели в конец
            if t1.reject and t2.reject:
                return 0
            elif t1.reject and t2.reject is None:
                return 1
            elif t1.reject is None and t2.reject:
                return -1

            # вычисляем весовые показатели
            if avg_times:
                t1_w_time = (1.0 * t1.time / avg_times) * Target.weight_time
                t2_w_time = (1.0 * t2.time / avg_times) * Target.weight_time
            else:
                t1_w_time = t2_w_time = 0

            if avg_costs:
                t1_w_cost = (1.0 * t1.cost / avg_costs) * Target.weight_cost
                t2_w_cost = (1.0 * t2.cost / avg_costs) * Target.weight_cost
            else:
                t1_w_cost = t2_w_cost = 0

            td_w_time = t1_w_time - t2_w_time
            td_w_cost = t1_w_cost - t2_w_cost

            res = td_w_time + td_w_cost
            if res > 0:
                return 1
            elif res < 0:
                return -1
            else:
                return 0

        # сортируем целевые значения
        targets.sort(cmp=compare)

    @staticmethod
    def optimal(targets):
        """
        Вернет первый неотклоненный целевой объект
        """
        return ([t for t in targets if t.reject is None] + [None])[0]

    @staticmethod
    def toStr(targets):
        """
        Вернет подробное текстовое представление целевых объектов
        """
        return '\n\n'.join([unicode(t) for t in targets])



class CarReject(Exception): pass


class Car(object):

    # плотность мусора
    DENSITY = 0.115

    def __init__(self, t, driver, overtime_max, overtime_coef, date):
        self.t = t
        self.overtime_coef = overtime_coef

        # получаем базу
        self.depot = t.transportdepot_set.all().last().depot
        # допустимые выгрузки
        self.landfills = list(t.type.landfills.all())
        # типы допустимых контейнеров
        self.container_types = set(t.type.container_types.values_list('id', flat=True))
        # типы допустимых ограничений
        self.platform_restricts = set(t.type.platform_restricts.values_list('id', flat=True))
        # водитель
        self.driver = driver

        # начало/конец рабочего дня
        start_time = make_aware(datetime.datetime.combine(date, self.driver.day_time_start or datetime.time(8)))
        finish_time = make_aware(datetime.datetime.combine(date, self.driver.day_time_finish or datetime.time(22)))
        # текущее время
        self.now_time = start_time

        # изначально все машины стартуют с базы
        self.now_point = self.depot
        # остаток рабочего времени
        self.left_time = (finish_time - start_time).total_seconds()
        # остаток переработки
        self.left_overtime = overtime_max

        # ссылки на стоимости
        self.cost_capacity = t.type.cost_capacity
        self.cost_work = t.type.cost_work
        self.cost_dist = t.type.cost_dist
        self.cost_idle = t.type.cost_idle

        # нормализация объема и массы
        self.capacity = float(t.type.capacity or (float(t.type.carrying_capacity or 0) / Car.DENSITY))
        self.carrying_capacity = float(t.type.carrying_capacity or (float(t.type.capacity or 0) * Car.DENSITY))

        # остаток по объему
        self.capacity_left = self.capacity
        # остаток по массе
        self.carrying_capacity_left = self.carrying_capacity

        # собираем маршрут
        self.route = []
        self.targets = []

        # выезд с базы
        self.addToRoute(self.depot, 0)

        LOG.info(u'Транспорт %s инициализирован', self.t)

    def __repr__(self):
        return repr(self.t)

    def __unicode__(self):
        return u'Трансопрт: %s. Местоположение: %s (%s). Текущее время: %s. Остаточный объем/масса: %s/%s' % (
            unicode(self.t),
            self.now_point._meta.verbose_name,
            self.now_point.address,
            self.now_time.strftime('%H:%M:%S'),
            self.capacity_left,
            self.carrying_capacity_left
        )

    def dist(self, start, finish):
        start_p = toPoint(start)
        finish_p = toPoint(finish)
        get_dist = lambda: int(1.0 * OsrmDistance.getDistance(start_p, finish_p))

        try:
            return get_dist()
        except Exception:
            OsrmDistance.addReq(start_p, finish_p)
            OsrmDistance.execute()
            return get_dist()

    def distSecond(self, dist):
        return int(1.0 * dist / self.t.type.speed_avg * 3600)

    def addToRoute(self, obj, time_to_point, time_proc=0):
        # увеличиваем текущее время
        self.now_time += datetime.timedelta(seconds=time_to_point)
        # собираем маршрут
        self.route.append((obj, self.now_time))
        # добавляем время обработки точки
        self.now_time += datetime.timedelta(seconds=time_proc)
        # время на точку
        time_point = time_to_point + time_proc

        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################

    def processTarget(self, target):
        # ссылка на контейнер
        cont = target.cont
        cont_capacity = cont.capacity or cont.type.capacity

        # добавляем в список целевой объект
        self.targets.append(target)

        # если контейнер не съемный
        if not cont.type.is_portable:
            # вычисляем новую остаточную массу и объем
            capacity_left = self.capacity_left - cont_capacity
            carrying_capacity_left = self.carrying_capacity_left - (cont_capacity * Car.DENSITY)

            # если не влазим - значит сначала предполагается заезд на выгрузку
            if capacity_left < 0 or carrying_capacity_left < 0:
                self.goToLandfill()

        # обработка контейнера
        def processCont():
            # время до контейнера в сек
            time_to_c = self.distSecond(self.dist(self.now_point, cont.platform))
            # смещаемся на новый контейнер
            self.now_point = cont.platform
            # остаток по объему
            self.capacity_left -= cont_capacity
            # остаток по массе
            self.carrying_capacity_left -= cont_capacity * Car.DENSITY
            # учет контейнера
            self.addToRoute(cont, time_to_c, cont.type.work_time)

        processCont()

        # если конетйнер съемный - отправляем на выгрузку и возвращаем контейнер на место
        if cont.type.is_portable:
            self.goToLandfill()
            processCont()


    def goToLandfill(self):
        # время от текущего положения до выгрузкок в сек
        time_to_landfills = [self.distSecond(self.dist(self.now_point, u)) for u in self.landfills]
        # берем самую ближ.
        time_to_landfill = min(time_to_landfills)
        landfill = self.landfills[time_to_landfills.index(time_to_landfill)]

        # смещаемся на выгрузку
        self.now_point = landfill
        # остаток по объему
        self.capacity_left = self.capacity

        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################

    def goHome(self):
        # если находимся на контейнере - сначала отправляем на выгрузку
        if isinstance(self.now_point, ContainerPlatform):
            self.goToLandfill()
        # время от выгрузки до базы в сек
        time_to_depot = self.distSecond(self.dist(self.now_point, self.depot))
        # учет базы
        self.addToRoute(self.depot, time_to_depot)
        # смещаемся на базу
        self.now_point = self.depot


class AlgBuildRoutes(object):

    def __init__(self, containers, transports, drivers, overtime_max, overtime_coef, weight_time=1, weight_cost=1, date=datetime.date.today()):
        # все аргументы обязательны
        if not containers:
            raise Exception(u'Список контейнеров не может быть пуст')
        if not transports:
            raise Exception(u'Список транспорта не может быть пуст')
        if not drivers:
            raise Exception(u'Список водителей не может быть пуст')

        self.containers = containers

        self.cars = []
        for transport in transports:
            # получаем список водителей для текущего ТС
            t_drivers = [d for d in drivers if (
                transport.id in {t.id for t in d.transports_allow.all()}
                or not len({t.id for t in d.transports_allow.all()})
            )]

            try:
                d = t_drivers.pop()
            except IndexError:
                LOG.warning(u'Для ТС %s не найден водитель!', unicode(transport))
                continue

            # создаем объект ТС
            self.cars.append(Car(transport, d, overtime_max, overtime_coef, date))
            # убираем водителя из списка доступных
            del drivers[drivers.index(d)]

        # режим OSRM - полный
        OsrmDistance.init(MODE_FULL)

        # веса стоимости и времени в контексте оптимизации
        Target.weight_time = weight_time
        Target.weight_cost = weight_cost


    def handle(self):
        # собираем уникальные базы и выгрузки
        d_depots = {car.depot.id: car.depot for car in self.cars}
        d_landfills = {u.id: u for u in chain(*[car.landfills for car in self.cars])}

        # список контейнеров, которые не были обработаны
        unhandled = []

        # строим связи между каждой базой и выгрузкой с каждой площадкой
        for c in self.containers:
            # с площадки на базу ехать нельзя
            for b in d_depots.values():
                OsrmDistance.addReq(toPoint(b), toPoint(c.platform))
            # можно ехать как с площадки на выгрузку, так и наоборот
            for u in d_landfills.values():
                OsrmDistance.addReq(toPoint(c.platform), toPoint(u))
                OsrmDistance.addReq(toPoint(u), toPoint(c.platform))

        # иожно ехать только с выгрузки на базу
        for u in d_landfills.values():
            for b in d_depots.values():
                OsrmDistance.addReq(toPoint(u), toPoint(b))

        OsrmDistance.execute()

        # строим общий маршрут
        containers = self.buildRoute()

        # алгоритм работает, пока все контейнеры не будут развезены
        for c in containers:
            # вычисляем целевые объекты
            targets = [Target(c, car) for car in self.cars]
            # сортируем целевые объекты
            Target.sort(targets)

            # получаем оптимальный объект
            target = Target.optimal(targets)

            # сохраняем текстовой вид обоснования
            setattr(c, 'rationale', Target.toStr(targets))
            # сохраняем оптимальный объект
            setattr(c, 'target', target)

            # отправляем оптимальную машину на укзанный контейнер
            if target:
                target.car.processTarget(target)
            # если нет машин с успешной вычисленной функцией - отмечаем соответствующе контейнер
            else:
                unhandled.append(c)

        # отправляем все машины в гараж
        for car in self.cars:
            car.goHome()

        # вернем список собранных данных по машинам
        return self.cars, unhandled

    def buildRoute(self):
        """
        Строим единый маршрут
        :return:
        """
        # собираем гео-точки, уникализируем
        points = [toPoint(c.platform) for c in self.containers]

        # обратная связь точек и контейнеров
        d_points = defaultdict(list)
        for c in self.containers:
            d_points[toStr(toPoint(c.platform))].append(c)

        alg = AlgTraveling(points)

        ##################################
        ## Часть кода пропущена в целях соблюдения конфидентиальности
        ##################################

        # на выходе получаем список контейнеров в порядке их объезда по гео-признаку
        return deque(chain(*[d_points[toStr(p)] for p in route]))
