import ccxt
import time
import logging

class BotBybit:
    def __init__(self, api_key, api_secret, symbol, initial_price, delta, mini_delta, lot, max_position):
        self.exchange = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',  # Торговля фьючерсами
                'recvWindow': 100000  # Увеличиваем временное окно до 20 секунд
            },
        })
        self.symbol = symbol
        self.initial_price = initial_price
        self.delta = delta
        self.mini_delta = mini_delta
        self.lot = lot
        self.max_position = max_position
        self.orders_table = []  # Плановая таблица заявок
        self.open_positions = []  # Список открытых позиций
        self.direction = None  # Направление движения цены
        self.position = 0  # Инициализируем текущую позицию как 0 (нет открытых позиций)
        self.runnint = True

    def get_current_position(self):
        """Получает текущую позицию с биржи."""
        try:
            positions = self.exchange.fetch_positions()  # Получаем все позиции
            print('positions = ', positions)
            for position in positions:
                if float(position['contracts']) > 0:  # Если есть открытая позиция
                    return float(position['contracts']), position['side']  # Возвращает размер позиции и сторону
            return 0, None  # Если позиций нет
        except Exception as e:
            print(f"Error fetching current position: {e}")
            return 0, None

    def get_open_orders(self):
        """Получает открытые заявки с биржи."""
        try:
            open_orders = self.exchange.fetch_open_orders(self.symbol)
            return open_orders
        except Exception as e:
            print(f"Error fetching open orders: {e}")
            return []

    def determine_direction(self, current_price):
        """Определяет направление движения цены."""
        if self.direction is None:  # Если направление еще не определено
            self.direction = "up" if current_price > self.initial_price else "down"
        else:
            # Если цена изменилась на величину больше или равную дельте, меняем направление
            if self.direction == "up" and current_price < self.initial_price - self.delta:
                self.direction = "down"
            elif self.direction == "down" and current_price > self.initial_price + self.delta:
                self.direction = "up"

    def update_orders_table(self, current_price):
        """Обновляет плановую таблицу заявок."""
        self.orders_table = []
        price = current_price

        # Получаем текущую позицию с биржи
        self.position, side = self.get_current_position()
        remaining_lot = self.max_position - self.position

        if remaining_lot <= 0:  # Если достигнут максимальный размер позиции
            return

        num_orders = int(remaining_lot // self.lot) + (1 if remaining_lot % self.lot != 0 else 0)
        new_lot_size = remaining_lot / num_orders

        for _ in range(num_orders):
            if self.direction == "up":
                price += self.delta
            elif self.direction == "down":
                price -= self.delta
            self.orders_table.append({'price': price, 'size': new_lot_size})
        #print(f"orders_table:,{self.orders_table}")

    def execute_order_with_stop_loss(self, side, size, stop_price):
        """Выполняет ордер с установкой стоп-лосса."""
        try:
            # Создаем маркет-заявку
            order = self.exchange.create_order(
                symbol=self.symbol,
                type='market',
                side=side,
                amount=size,
            )
            print(f"Executed market order: Side={side}, Size={size}, OrderID={order['id']}")

            # Устанавливаем стоп-лосс
            self.exchange.private_post_position_trading_stop({
                'symbol': self.symbol,
                'side': side,
                'stop_loss': stop_price,
            })
            print(f"Set stop loss for position: ID={order['id']}, StopPrice={stop_price}")
            return order
        except Exception as e:
            print(f"Error executing order with stop loss: {e}")
            return None

    def set_initial_stop_loss(self, position):
        """
        Устанавливает начальный стоп-лосс для новой позиции.
        """
        try:
            side = position['side']
            entry_price = position['price']  # Цена входа

            # Рассчитываем уровень стоп-лосса
            if side == "buy":  # Для длинной позиции (long)
                stop_loss = entry_price - self.delta
            elif side == "sell":  # Для короткой позиции (short)
                stop_loss = entry_price + self.delta

            # Устанавливаем стоп-лосс через API
            self.exchange.private_post_position_trading_stop({
                'symbol': self.symbol,
                'side': side,
                'stop_loss': stop_loss,
            })
            print(f"Set initial stop loss for {side} position: StopLoss={stop_loss}")

            # Добавляем флаг, что стоп-лосс еще не был изменен
            position['stop_loss_moved'] = False
        except Exception as e:
            print(f"Error setting initial stop loss: {e}")

    def update_stop_loss_for_positions(self, current_price):
        """
        Переставляет стоп-лосс для открытых позиций, если цена ушла выше/ниже на delta.
        """
        try:
            for position in self.open_positions:
                side = position['side']
                entry_price = position['price']
                stop_loss_moved = position.get('stop_loss_moved', False)

                # Если стоп-лосс уже был изменён, пропускаем эту позицию
                if stop_loss_moved:
                    continue

                # Проверяем, нужно ли переставить стоп-лосс
                if side == "buy" and current_price >= entry_price + self.delta:
                    new_stop_loss = entry_price - self.delta + self.mini_delta
                elif side == "sell" and current_price <= entry_price - self.delta:
                    new_stop_loss = entry_price + self.delta - self.mini_delta
                else:
                    continue  # Стоп-лосс не нужно менять

                # Обновляем стоп-лосс через API
                self.exchange.private_post_position_trading_stop({
                    'symbol': self.symbol,
                    'side': side,
                    'stop_loss': new_stop_loss,
                })
                print(f"Updated stop loss for {side} position: NewStopLoss={new_stop_loss}")

                # Устанавливаем флаг, что стоп-лосс уже изменён
                position['stop_loss_moved'] = True
        except Exception as e:
            print(f"Error updating stop loss: {e}")

    def monitor(self):
        """Мониторинг состояния: получение данных с биржи."""
        try:
            # Получаем текущую цену
            current_price = self.exchange.fetch_ticker(self.symbol)['last']
            print(f"Current price: {current_price}")

            # Получаем текущую позицию
            new_position, position_side = self.get_current_position()

            # Проверяем, изменилась ли позиция
            if new_position != self.position:
                print(f"Position changed: Old={self.position}, New={new_position}")
                self.position = new_position  # Обновляем текущую позицию
                self.update_orders_table(current_price)  # Пересчитываем таблицу заявок

            # Определяем направление движения цены
            self.determine_direction(current_price)

            # Передаем данные в метод trade
            self.trade(current_price)
        except Exception as e:
            print(f"Error during monitoring: {e}")

    def trade(self, current_price):
        """Торговые действия: выставление ордеров и пересчет таблицы заявок."""
        # Обновляем плановую таблицу заявок
        self.update_orders_table(current_price)

        # Проверяем, нужно ли выставлять новые ордера
        for order in self.orders_table[:]:  # Используем копию списка для безопасного изменения
            if (self.direction == "up" and current_price >= order['price']) or \
                    (self.direction == "down" and current_price <= order['price']):
                # Если цена достигла уровня заявки, выставляем маркет-ордер
                side = "buy" if self.direction == "up" else "sell"
                new_order = self.execute_order_with_stop_loss(side, order['size'], order['price'])

                if new_order:
                    # Добавляем позицию в список открытых позиций
                    position = {
                        'id': new_order['id'],
                        'price': order['price'],
                        'size': order['size'],
                        'side': side,
                    }
                    self.open_positions.append(position)

                    # Удаляем выполненную заявку из таблицы
                    self.orders_table.remove(order)

        # Переставляем стоп-лосс для открытых позиций
        self.update_stop_loss_for_positions(current_price)

    def stop_bot(self):
        """Выключение бота. - Пока дополнительный функционал"""
        print("Начинаю выключение бота...")

        # Отменяем все открытые ордера
        #self.cancel_all_orders()

        # Закрываем все открытые позиции
        #self.close_all_positions()

        # Останавливаем основной цикл работы бота
        self.running = False
        print("Бот успешно выключен.")


    def run(self):
        """Основной цикл работы бота."""
        while True:
            try:
                self.monitor()
                time.sleep(5)  # Пауза между итерациями
                print(f"Работаю")
            except Exception as e:
                logging.error(f"Ошибка: {e}")
                time.sleep(5)

bot = BotBybit(
    api_key=API_KEY,
    api_secret=API_SECRET,
    symbol="SOL/USDT:USDT",#фьючерс perp # спот =  SOLUSDT
    initial_price=147,
    delta=3,
    mini_delta=1,
    lot=0.1,
    max_position=1,
)

bot.run()
