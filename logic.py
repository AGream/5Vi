import datetime
import json
import logging
import os
import re
import sys
import threading
import time
import traceback

import cv2
import easyocr
import keyboard # Предполагается установленной (pip install keyboard)
import mss # Предполагается установленной (pip install mss)
import numpy as np
import pyautogui # Предполагается установленной (pip install pyautogui)

# --- Сторонние библиотеки ---
try:
    from transliterate import get_available_language_codes, translit
    TRANS_AVAILABLE = True
except ImportError:
    print("!!! Внимание: Библиотека 'transliterate' не найдена.", file=sys.stderr)
    def translit(text, lang_code, reversed=False): return text # Заглушка
    def get_available_language_codes(): return [] # Заглушка
    TRANS_AVAILABLE = False


# --- Определение базовой директории ПЕРЕД импортом констант ---
# Это дублируется в main.py, но нужно здесь, чтобы константы могли
# использовать BASE_DIR при своем определении.
try:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # В режиме PyInstaller (one-file) _MEIPASS - это временная папка,
        # но нам нужна папка, где лежит сам .exe.
        BASE_DIR = os.path.dirname(sys.executable)
    elif '__file__' in globals():
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    else:
        BASE_DIR = os.getcwd() # Fallback
except Exception:
    BASE_DIR = os.getcwd()


# --- Локальные импорты ---
try:
    from PyQt6 import QtCore
    from PyQt6.QtCore import (
        QMetaObject,
        QObject,
        QPoint,
        QRect,
        QSize,
        Qt,
        QThread,
        QTimer,
        pyqtSignal,
        pyqtSlot,
        Q_ARG # Добавлен Q_ARG для invokeMethod
    )
    from PyQt6.QtWidgets import QApplication, QMessageBox

    # Импорт констант после определения BASE_DIR
    from constants import (
        ADD_ITEM_HOTKEY,
        DEBUG_SAVE_PRICE_ROI,
        DEBUG_PRICE_ROI_PATH,
        DEFAULT_ITEM_ENABLED,
        DEFAULT_ITEM_MAX_PRICE,
        DEFAULT_ITEM_QUANTITY,
        ITEM_DATA_FILE,
        LOG_FILE_NAME,
        MIN_REFRESH_INTERVAL,
        OCR_LANGUAGES,
        OCR_PRICE_ALLOWLIST,
        POST_ACTION_PAUSE,
        PRICE_SEARCH_RELATIVE_AREA, # НОВАЯ КОНСТАНТА
        PRICE_OCR_CONFIDENCE_THRESHOLD, # НОВАЯ КОНСТАНТА
        PRICE_MIN_HORIZONTAL_OFFSET_FROM_TEMPLATE_LEFT, # НОВАЯ КОНСТАНТА
        PRICE_MIN_VERTICAL_OFFSET_FROM_TEMPLATE_BOTTOM, # НОВАЯ КОНСТАНТА
        PRICE_MAX_VERTICAL_OFFSET_FROM_TEMPLATE_BOTTOM, # НОВАЯ КОНСТАНТА
        REFRESH_BUTTON_X,
        REFRESH_BUTTON_Y,
        REFRESH_PAUSE,
        SCAN_AREA,
        SCAN_INTERVAL_WHEN_NOT_FOUND,
        STOP_MONITORING_HOTKEY,
        TARGET_WINDOW_TITLE, # Пока не используется
        TEMPLATE_FOLDER,
        TEMPLATE_MATCH_THRESHOLD,
        WORKER_LOOP_PAUSE,
    )
    from screen_selector import ScreenSelectionWidget # Импорт виджета выделения

    PYQT_AVAILABLE = True
except ImportError as import_err:
    print(f"!!! КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА PyQt6 или локальных модулей: {import_err}", file=sys.stderr)
    # Попытка показать сообщение, если QApplication уже создан main.py
    app = QApplication.instance()
    if app:
        try:
            QMessageBox.critical(
                None,
                "Ошибка Загрузки",
                f"Не удалось импортировать модули: {import_err}\n"
                "Убедитесь, что все файлы и библиотеки установлены правильно.\n"
                "Приложение будет закрыто."
            )
        except Exception:
            pass # Игнорируем ошибку, если QMessageBox не работает
    sys.exit(1) # Всегда выходим при критической ошибке импорта

# --- Определение путей к ресурсам ---
ABS_TEMPLATE_FOLDER = os.path.join(BASE_DIR, TEMPLATE_FOLDER)
ABS_ITEM_DATA_FILE = os.path.join(BASE_DIR, ITEM_DATA_FILE)
LOG_FILE_PATH = os.path.join(BASE_DIR, LOG_FILE_NAME)
ABS_DEBUG_PRICE_ROI_PATH = os.path.join(BASE_DIR, DEBUG_PRICE_ROI_PATH)


# --- Настройка логирования ---
# Убедимся, что логгер не настроен повторно, если модуль перезагружается
if not logging.getLogger(__name__).handlers:
    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-5.5s] [%(threadName)s] %(message)s"
    )
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    try:
        # Используем RotatingFileHandler для предотвращения слишком большого файла лога
        from logging.handlers import RotatingFileHandler
        # 5MB макс размер, 1 бэкап файл
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH, mode="w", maxBytes=5*1024*1024, backupCount=1, encoding="utf-8"
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
        logger.info(f"Логирование настроено в файл: {LOG_FILE_PATH}")
    except Exception as log_setup_err:
        # Если не удалось настроить файл-логер, выводим ошибки только в stderr
        print(f"!!! ОШИБКА НАСТРОЙКИ ЛОГ-ФАЙЛА: {log_setup_err}", file=sys.stderr)
        # Добавляем StreamHandler для вывода логов в консоль/stderr
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(log_formatter)
        logger.addHandler(stream_handler)
        logger.warning("Логи будут выводиться только в консоль/stderr.")


logger.info("=" * 50)
logger.info("Логика приложения инициализируется...")
logger.info(f"Base dir: {BASE_DIR}")
logger.info(f"Template folder: {ABS_TEMPLATE_FOLDER}")
logger.info(f"Item data file: {ABS_ITEM_DATA_FILE}")
logger.info(f"Log file: {LOG_FILE_PATH}")
logger.info(f"Debug Save Price ROI: {DEBUG_SAVE_PRICE_ROI}")
if DEBUG_SAVE_PRICE_ROI:
    logger.info(f"Debug Price ROI Path: {ABS_DEBUG_PRICE_ROI_PATH}")
logger.info(f"PyQt Available: {PYQT_AVAILABLE}")
logger.info(f"Transliterate Available: {TRANS_AVAILABLE}")
logger.info("=" * 50)


# --- Глобальная блокировка для pyautogui ---
# Это необходимо, чтобы избежать одновременных вызовов pyautogui из разных потоков,
# что может привести к непредсказуемому поведению или ошибкам.
input_lock = threading.RLock()


# ============================================================================
# === Класс Worker: Фоновый исполнитель задач ===
# ============================================================================
class Worker(QObject):
    """
    Выполняет поиск и действия в отдельном потоке.
    Логирование в файл. Усиленная проверка остановки.
    """

    # Сигналы для отправки данных обратно в основной поток (BotLogic/Interface)
    finished = pyqtSignal(bool) # bool: True если остановлен по достижению цели
    error = pyqtSignal(str) # Сигнал об ошибке (не критической для краха потока)
    action_performed_signal = pyqtSignal(str, int, int) # name, price, total_bought

    def __init__(self, items_to_search: list, ocr_reader: easyocr.Reader):
        super().__init__()
        # Устанавливаем имя потока для логирования. Делаем это в run(),
        # т.к. поток QThread создается и запускается извне.
        # threading.current_thread().name = f"Worker_{id(self)}"

        logger.info("Инициализация Worker...")
        # Копируем данные, чтобы Worker работал с собственной копией
        self.items_data = [item.copy() for item in items_to_search]
        self.ocr_reader = ocr_reader # Reader передается из основного потока
        self.templates = {} # Загруженные шаблоны OpenCV
        self.item_progress = {} # Словарь для отслеживания купленного кол-ва
        self._stop_event = threading.Event() # Событие для надежной остановки Worker'а
        self.scan_area_coords = None # Координаты области сканирования
        self.sct = None # MSS скриншоттер
        self.last_refresh_time = 0 # Время последнего обновления списка в игре
        self.all_targets_reached = False # Флаг, были ли достигнуты все цели

        # Загрузка шаблонов и инициализация прогресса происходит в __init__
        # для проверки данных до запуска потока.
        try:
            self._load_templates()
        except Exception:
            # Если загрузка шаблонов не удалась, логируем и обнуляем список
            logger.exception(
                f"[Worker] Критическая ошибка при загрузке шаблонов:"
            )
            self.items_data = [] # Очищаем список товаров для поиска

        # Проверка, есть ли вообще что искать после загрузки шаблонов
        if not self.items_data:
            logger.warning(
                f"[Worker] Нет валидных товаров для поиска после загрузки шаблонов."
            )
        else:
             logger.info(f"[Worker] Worker инициализирован с {len(self.items_data)} товарами.")

    @property
    def _is_running(self) -> bool:
        """
        Проверяет, был ли запрошен останов.
        Комбинирует проверку threading.Event и флага прерывания потока Qt.
        """
        # Проверка флага из threading.Event
        if self._stop_event.is_set():
            return False

        # Проверка флага прерывания потока Qt
        qt_thread = QtCore.QThread.currentThread()
        if qt_thread and qt_thread.isInterruptionRequested():
            # Если поток Qt запросил прерывание, устанавливаем и наше событие
            # для синхронизации и более быстрого выхода из блокирующих sleep
            self._stop_event.set()
            return False

        return True # Если ни один флаг не установлен, значит поток должен работать

    def _load_templates(self):
        """
        Загружает шаблоны OpenCV из файлов и инициализирует item_progress.
        Вызывается в __init__ Worker'а.
        """
        logger.info(f"[Worker] Загрузка шаблонов...")
        valid_items_temp = [] # Временный список для валидных товаров
        self.templates.clear() # Очищаем предыдущие шаблоны
        self.item_progress.clear() # Очищаем предыдущий прогресс

        for item_data in self.items_data:
            # Проверка остановки во время загрузки шаблонов (хотя обычно быстро)
            if not self._is_running:
                logger.warning("[Worker] Загрузка шаблонов прервана.")
                break # Прерываем цикл, если запрошена остановка

            item_name = item_data.get("name")
            template_path = item_data.get("template_path")
            target_qty = item_data.get("quantity", DEFAULT_ITEM_QUANTITY) # Целевое количество

            # Базовая проверка данных
            if not item_name or not isinstance(item_name, str):
                logger.warning(f"[Worker] Пропущен товар с некорректным именем: {item_name}")
                continue
            if item_name in self.templates:
                logger.warning(f"[Worker] Пропущен дубликат товара в списке: '{item_name}'")
                continue
            if not template_path or not isinstance(template_path, str):
                 logger.warning(f"[Worker] Пропущен товар '{item_name}': отсутствует путь к шаблону.")
                 continue
            if not os.path.isabs(template_path):
                 # Конвертируем относительный путь в абсолютный, если необходимо
                 # (Хотя логика сохранения в BotLogic должна сохранять абсолютные)
                 abs_path = os.path.abspath(os.path.join(BASE_DIR, template_path))
                 logger.warning(f"[Worker] Конвертация относительного пути для '{item_name}': {template_path} -> {abs_path}")
                 template_path = abs_path


            if not os.path.exists(template_path):
                logger.error(
                    f"[Worker] Шаблон НЕ НАЙДЕН для '{item_name}' "
                    f"по пути '{template_path}'. Пропуск."
                )
                continue # Пропускаем этот товар

            try:
                # Загружаем изображение шаблона в оттенках серого
                template_img = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
                if template_img is None:
                    raise ValueError(
                        f"OpenCV не смог загрузить изображение из: {template_path}"
                    )

                # Проверяем размер шаблона (должен быть больше 3x3 пикселей)
                h, w = template_img.shape[:2]
                if w < 3 or h < 3:
                    logger.warning(
                        f"[Worker] Шаблон '{item_name}' слишком мал "
                        f"({w}x{h}px). Пропуск."
                    )
                    continue # Пропускаем слишком маленькие шаблоны

                # Если все проверки пройдены, добавляем шаблон и инициализируем прогресс
                self.templates[item_name] = template_img
                self.item_progress[item_name] = {
                    "bought": 0, # Сбрасываем счетчик при каждом запуске Worker'а
                    "target": max(1, target_qty), # Цель должна быть минимум 1
                }
                 # Добавляем товар во временный список валидных
                valid_items_temp.append(item_data)

            except Exception:
                # Логируем любую другую ошибку при загрузке конкретного шаблона
                logger.exception(
                    f"[Worker] Ошибка при загрузке и проверке шаблона "
                    f"'{item_name}' по пути '{template_path}':"
                )
                continue # Пропускаем этот товар

        # Обновляем основной список товаров Worker'а только валидными товарами
        self.items_data = valid_items_temp
        num_valid = len(self.items_data)

        if num_valid > 0:
            logger.info(
                f"[Worker] Загрузка шаблонов завершена. Обрабатывается {num_valid} валидных товаров."
            )
        else:
            logger.warning(
                f"[Worker] Загрузка шаблонов завершена. Не найдено ни одного "
                f"валидного шаблона для поиска."
            )

    def _get_screen_area_for_scan(self) -> bool:
        """
        Определяет координаты области экрана для сканирования.
        Приоритет: SCAN_AREA из констант, затем основной монитор MSS.
        Возвращает True, если область успешно определена, False иначе.
        """
        logger.info(f"[Worker] Определение области сканирования...")
        coords_ok = False
        required_keys = ["left", "top", "width", "height"] # Ключи, необходимые для dict области

        # Убедимся, что MSS инициализирован
        if self.sct is None:
            logger.error(f"[Worker] MSS (sct) не инициализирован!")
            return False

        # 1. Проверка SCAN_AREA из constants.py
        if (
            SCAN_AREA
            and isinstance(SCAN_AREA, dict)
            and all(k in SCAN_AREA for k in required_keys)
        ):
            try:
                sa = SCAN_AREA
                # Проверяем, что все значения - int и размеры положительные
                is_valid = (
                    all(isinstance(sa.get(k), int) for k in required_keys)
                    and sa.get("width", 0) > 0
                    and sa.get("height", 0) > 0
                )
                if is_valid:
                    # Получаем размеры всего виртуального экрана для проверки границ
                    # Используем geometry монитора 0 в MSS, которая представляет весь виртуальный рабочий стол
                    monitors = self.sct.monitors
                    if len(monitors) > 0:
                         virtual_screen = monitors[0] # Индекс 0 - это весь виртуальный экран
                         w_scr, h_scr = virtual_screen["width"], virtual_screen["height"]
                         # Проверяем, что область не выходит за границы виртуального экрана
                         is_within_bounds = (
                             sa["left"] >= virtual_screen["left"]
                             and sa["top"] >= virtual_screen["top"]
                             and sa["left"] + sa["width"] <= virtual_screen["left"] + w_scr
                             and sa["top"] + sa["height"] <= virtual_screen["top"] + h_scr
                         )

                         if is_within_bounds:
                            self.scan_area_coords = sa.copy()
                            coords_ok = True
                            logger.info(
                                f"[Worker] Используется SCAN_AREA из констант: "
                                f"{self.scan_area_coords}"
                            )
                         else:
                            logger.error(
                                f"[Worker] SCAN_AREA {sa} выходит за границы виртуального экрана ({virtual_screen}). Игнорируется."
                            )
                    else:
                         logger.error("[Worker] MSS не обнаружил ни одного монитора, невозможно проверить SCAN_AREA.")


                else:
                    logger.error(
                        f"[Worker] SCAN_AREA невалидна (не int или нулевые размеры): {sa}. Игнорируется."
                    )
            except Exception:
                logger.exception(
                    f"[Worker] Ошибка валидации или получения размеров виртуального экрана для SCAN_AREA:"
                )

        # 2. Если SCAN_AREA невалидна или не задана, используем основной монитор MSS
        if not coords_ok:
            try:
                monitors = self.sct.monitors # monitors[0] - виртуальный десктоп, monitors[1+] - физ.мониторы
                if len(monitors) > 1:
                    # MSS часто имеет монитор 1 как основной физический
                    info = monitors[1]
                    logger.info(
                        f"[Worker] SCAN_AREA не задана/невалидна. Используется основной физический монитор: {info}"
                    )
                elif len(monitors) == 1:
                    # Если только один монитор, он может быть как monitors[0] (виртуальный == физический)
                    # или как monitors[1] с monitors[0] как псевдо-виртуальным
                    # Проверим monitors[0] как возможный единственный физический
                    info = monitors[0]
                    logger.info(
                        f"[Worker] SCAN_AREA не задана/невалидна. Используется единственный монитор (monitors[0]): {info}"
                    )
                else:
                    logger.error(
                        f"[Worker] MSS не обнаружил мониторов! Невозможно определить область сканирования."
                    )
                    return False # Не удалось определить область

                # Удаляем ненужные ключи типа 'scale', 'retina'
                info.pop("scale", None)
                info.pop("retina", None)
                self.scan_area_coords = info.copy()
                coords_ok = True
                logger.info(f"[Worker] Область сканирования определена как: {self.scan_area_coords}")

            except Exception:
                logger.exception(f"[Worker] КРИТИЧЕСКАЯ ошибка при попытке получить информацию о мониторах из MSS:")
                coords_ok = False # Снова ошибка

        if not coords_ok:
            logger.error(
                f"[Worker] Не удалось определить область сканирования!"
                f" Проверьте SCAN_AREA в constants.py или настройки мониторов."
            )
        return coords_ok

    @pyqtSlot()
    def run(self):
        """
        Основной цикл работы Worker'а.
        Захват экрана, поиск шаблонов, проверка цен, выполнение действий.
        Выполняется в отдельном QThread.
        """
        # Устанавливаем имя потока здесь, т.к. run() вызывается уже в созданном потоке QThread
        threading.current_thread().name = f"WorkerThread_{id(self)}"
        self.worker_id = threading.current_thread().name

        self._stop_event.clear() # Сбрасываем флаг остановки перед началом
        self.all_targets_reached = False # Сбрасываем флаг достижения цели
        logger.info(f"[{self.worker_id}] >>> Worker запущен. Начало основного цикла поиска.")

        # Проверка наличия товаров для поиска
        if not self.items_data:
            logger.warning(f"[{self.worker_id}] Нет товаров для поиска. Завершение Worker.")
            self.finished.emit(False) # Завершаем без достижения цели
            return

        # Инициализация MSS
        try:
            if not self._is_running:
                raise SystemExit("Остановка до инициализации MSS")
            self.sct = mss.mss()
            logger.info(f"[{self.worker_id}] MSS инициализирован для Worker'а.")
            if not self._is_running:
                raise SystemExit("Остановка после инициализации MSS")
        except Exception:
            logger.exception(f"[{self.worker_id}] КРИТИЧЕСКАЯ ошибка инициализации MSS:")
            self.error.emit("Ошибка инициализации захвата экрана (MSS).")
            self.finished.emit(False) # Завершаем с ошибкой
            return

        # Определение области сканирования
        if not self._get_screen_area_for_scan():
            logger.error(f"[{self.worker_id}] Не удалось определить область сканирования. Завершение Worker.")
            self.error.emit("Не удалось определить область сканирования.")
            try:
                self.sct.close() # Пытаемся закрыть MSS при ошибке
            except Exception:
                pass
            self.sct = None
            self.finished.emit(False) # Завершаем с ошибкой
            return

        # Инициализация времени последнего обновления
        self.last_refresh_time = time.monotonic()
        logger.info(f"[{self.worker_id}] Основной цикл поиска запущен.")

        try:
            # --- ОСНОВНОЙ ЦИКЛ ПОИСКА ---
            while self._is_running:
                # Очень частая проверка флага остановки в начале каждой итерации
                if not self._is_running:
                    break

                action_taken_this_loop = False # Флаг, было ли выполнено действие в этой итерации
                items_processed_this_loop = set() # Множество имен товаров, которые уже обработали в этом скане

                try:
                    # --- 1. Захват экрана ---
                    if not self._is_running:
                        break
                    # Убедимся, что sct не None перед использованием
                    if self.sct is None or self.scan_area_coords is None:
                         logger.error(f"[{self.worker_id}] Ресурсы захвата экрана недоступны в цикле.")
                         if not self._sleep_interruptible(1.0):
                             break # Пауза перед повторной попыткой
                         continue # Пропускаем текущую итерацию
                    try:
                        img_grab = self.sct.grab(self.scan_area_coords)
                        if not self._is_running:
                            break
                    except mss.ScreenShotError as e:
                        logger.warning(f"[{self.worker_id}] Ошибка захвата экрана MSS: {e}. Пауза 1с.")
                        if not self._sleep_interruptible(1.0):
                            break
                        continue # Пропускаем текущую итерацию при ошибке захвата
                    except Exception as e:
                        logger.exception(f"[{self.worker_id}] Неожиданная ошибка при захвате экрана:")
                        if not self._sleep_interruptible(1.0):
                            break
                        continue

                    img_bgra = np.array(img_grab)

                    # Проверка на пустой кадр
                    if img_bgra.size == 0:
                        logger.warning(f"[{self.worker_id}] Захвачен пустой кадр ({self.scan_area_coords}). Пауза 0.5с.")
                        if not self._sleep_interruptible(0.5):
                            break
                        continue # Пропускаем текущую итерацию

                    # Конвертация для OpenCV и OCR
                    gray = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2GRAY)
                    bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR) # BGR для сохранения ROI

                    # --- 2. Итерация по активным товарам ---
                    # Фильтруем только те товары, которые включены и еще не достигли цели
                    active_items = [
                        item for item in self.items_data
                        if item.get("name") in self.item_progress # Проверка наличия в прогрессе
                        and item.get("enabled", False) # Проверка, что товар включен
                        and self.item_progress[item["name"]]["bought"]
                        < self.item_progress[item["name"]]["target"] # Проверка, что цель не достигнута
                    ]

                    if not active_items and self.item_progress:
                         # Если нет активных товаров, но есть товары в списке, возможно,
                         # все цели достигнуты или все отключены.
                         # Проверим, все ли цели достигнуты.
                         all_done_check = all(
                             p["bought"] >= p["target"]
                             for p in self.item_progress.values()
                         )
                         if all_done_check and self.item_progress:
                              logger.info(f"[{self.worker_id}] Все цели достигнуты. Завершение Worker.")
                              self.all_targets_reached = True
                              self.stop()
                              break # Устанавливаем флаг и останавливаем

                         # Если не все цели достигнуты (значит, часть отключена или нет шаблона),
                         # просто продолжаем цикл (возможно, пользователь включит товар позже)
                         # Если нет активных, просто ждем следующей итерации или обновления

                    for item_data in active_items:
                        if not self._is_running:
                            break # Проверка остановки перед обработкой каждого товара

                        name = item_data.get("name")
                        tmpl = self.templates.get(name) # Получаем шаблон из загруженных
                        target_price = item_data.get("max_price", DEFAULT_ITEM_MAX_PRICE) # Макс. цена из данных
                        current_progress = self.item_progress.get(name) # Прогресс по этому товару

                        # Проверки на корректность данных товара и шаблона
                        if tmpl is None or current_progress is None or name in items_processed_this_loop:
                            continue # Пропускаем, если нет шаблона/прогресса или уже обработали в этом скане

                        h, w = tmpl.shape[:2]
                        if w == 0 or h == 0:
                            logger.warning(f"[{self.worker_id}] Шаблон '{name}' имеет нулевые размеры. Пропуск.")
                            continue

                        # --- 3. Поиск шаблона ---
                        if not self._is_running:
                            break
                        try:
                            # Выполняем поиск шаблона по серому изображению области сканирования
                            res = cv2.matchTemplate(
                                gray, tmpl, cv2.TM_CCOEFF_NORMED
                            )
                            if not self._is_running:
                                break

                            # Находим лучшее совпадение
                            _, max_val, _, max_loc = cv2.minMaxLoc(res)
                            if not self._is_running:
                                break

                        except cv2.error as e:
                            logger.error(f"[{self.worker_id}] Ошибка cv2.matchTemplate для '{name}': {e}")
                            continue # Пропускаем товар при ошибке CV
                        except Exception:
                            logger.exception(f"[{self.worker_id}] Неожиданная ошибка при поиске шаблона для '{name}':")
                            continue

                        # --- 4. Обработка найденного совпадения ---
                        if max_val >= TEMPLATE_MATCH_THRESHOLD:
                            # Шаблон найден с достаточной уверенностью
                            logger.info(f"[{self.worker_id}] Шаблон '{name}' найден с уверенностью {max_val:.2f} на {max_loc}.")

                            # Координаты верхнего левого угла НАЙДЕННОГО шаблона на СКРИНШОТЕ области сканирования
                            template_x_in_scan = max_loc[0]
                            template_y_in_scan = max_loc[1]
                            template_w_in_scan = w
                            template_h_in_scan = h


                            # Координаты верхнего левого угла НАЙДЕННОГО шаблона на ВСЕМ ЭКРАНЕ
                            template_x_global = self.scan_area_coords["left"] + template_x_in_scan
                            template_y_global = self.scan_area_coords["top"] + template_y_in_scan

                            # Bounding box найденного шаблона в ГЛОБАЛЬНЫХ координатах
                            template_bbox_global = {
                                "left": template_x_global,
                                "top": template_y_global,
                                "width": template_w_in_scan,
                                "height": template_h_in_scan
                            }

                            items_processed_this_loop.add(name) # Помечаем товар как обработанный в этом скане

                            if not self._is_running:
                                break

                            # --- 5. Поиск и проверка цены в области ---
                            price, price_ok = self._find_and_check_price(
                                template_bbox_global,       # Глобальные коорд. бокса названия
                                (template_x_in_scan, template_y_in_scan, template_w_in_scan, template_h_in_scan), # Коорд/размер бокса названия в скане
                                item_data,                  # Данные товара
                                bgr                         # BGR изображение области сканирования
                            )
                            if not self._is_running:
                                break

                            # --- 6. Выполнение действия ---
                            if price_ok:
                                logger.info(f"[{self.worker_id}] Цена {price}$ для '{name}' ({current_progress['bought']}/{current_progress['target']}) соответствует условию ({target_price if target_price > 0 else 'Любая'}$)")
                                if not self._is_running:
                                    break
                                # Выполняем клик и Esc
                                success = self._perform_item_action(
                                    template_bbox_global, item_data, price
                                )
                                if not self._is_running:
                                    break

                                if success:
                                    action_taken_this_loop = True # Флаг, что действие было выполнено
                                    # Пауза после действия, чтобы игра успела отреагировать
                                    if not self._sleep_interruptible(
                                        POST_ACTION_PAUSE
                                    ):
                                        break # Если пауза прервана, выходим из цикла worker

                            else:
                                 if target_price > 0 and price is not None:
                                     logger.info(f"[{self.worker_id}] Цена {price}$ для '{name}' ВЫШЕ лимита {target_price}$. Действие не выполнено.")
                                 elif price is None:
                                      logger.warning(f"[{self.worker_id}] Не удалось найти/распознать валидную цену для '{name}'. Действие не выполнено.")
                                 # Действие не выполнено, продолжаем поиск или ждем следующей итерации

                        # --- Конец обработки найденного совпадения для товара ---
                        if not self._is_running:
                            break # Еще одна проверка перед следующим товаром


                    # --- Конец итерации по всем активным товарам ---
                    if not self._is_running:
                        break

                    # --- 7. Проверка достижения ВСЕХ целей ---
                    # Проверяем только если есть товары в item_progress (т.е. не пустой список)
                    all_done = (
                        all(
                            p["bought"] >= p["target"]
                            for p in self.item_progress.values()
                        ) if self.item_progress else False
                    )
                    if all_done:
                        logger.info(f"[{self.worker_id}] !!! ВСЕ ЦЕЛИ ДЛЯ АКТИВНЫХ ТОВАРОВ ДОСТИГНУТЫ !!! Остановка Worker.")
                        self.all_targets_reached = True
                        self.stop()
                        break # Устанавливаем флаг и останавливаем Worker

                    if not self._is_running:
                        break # Финальная проверка перед паузой/обновлением

                    # --- 8. Обновление списка в игре или пауза ---
                    now = time.monotonic()
                    # Если не было выполнено ни одного действия в этом цикле сканирования
                    # И прошло достаточно времени с последнего обновления
                    needs_refresh = (
                        not action_taken_this_loop
                        and (REFRESH_BUTTON_X is not None and REFRESH_BUTTON_Y is not None) # Только если кнопка Обновить задана
                        and (now - self.last_refresh_time > MIN_REFRESH_INTERVAL)
                    )

                    if needs_refresh:
                        if not self._is_running:
                            break
                        logger.info(f"[{self.worker_id}] Ничего не найдено/куплено за долгий период. Попытка обновить список в игре.")
                        self._try_refresh_list() # Кликаем по кнопке Обновить
                        if not self._is_running:
                            break
                        # Пауза после клика "Обновить", чтобы список успел прогрузиться
                        if not self._sleep_interruptible(REFRESH_PAUSE):
                            break
                    elif not action_taken_this_loop: # Пауза, только если не было действия и не было обновления
                         # Делаем короткую паузу для снижения нагрузки на CPU
                         if not self._sleep_interruptible(WORKER_LOOP_PAUSE):
                             break


                # --- Обработка исключений внутри цикла ---
                # Эти исключения не должны приводить к краху всего Worker'а,
                # только к пропуску текущей итерации цикла while.
                except mss.ScreenShotError as e:
                    logger.warning(f"[{self.worker_id}] MSS grab Error в цикле: {e}. Пауза 1с.")
                    if not self._sleep_interruptible(1.0):
                        break
                except cv2.error as e:
                    logger.error(f"[{self.worker_id}] OpenCV Error в цикле: {e}. Пауза 0.5с.")
                    if not self._sleep_interruptible(0.5):
                        break
                except SystemExit as e:
                    # Перехват SystemExit, если где-то в коде он вызван
                    logger.info(f"[{self.worker_id}] Получен SystemExit: {e}. Завершение Worker.")
                    self.stop()
                    break # Останавливаем Worker
                except Exception:
                    # Ловим все остальные неожиданные ошибки в цикле
                    logger.exception(f"[{self.worker_id}] КРИТИЧЕСКАЯ НЕОЖИДАННАЯ ошибка в основном цикле поиска:")
                    # При критической ошибке в цикле, возможно, лучше остановиться
                    self.error.emit(f"Критическая ошибка в цикле поиска: {sys.exc_info()[0].__name__}")
                    self.stop()
                    break # Останавливаем Worker

            # --- Конец основного цикла while ---
            log_status = (
                f"Worker завершает работу. "
                f"is_running={self._is_running}, "
                f"all_targets_reached={self.all_targets_reached}"
            )
            logger.info(log_status)
        finally:
            # --- Очистка ресурсов Worker'а ---
            logger.info(f"[{self.worker_id}] Начинается очистка ресурсов Worker'а...")
            if self.sct:
                try:
                    self.sct.close()
                    logger.info(f"[{self.worker_id}] MSS закрыт.")
                except Exception as e:
                     logger.error(f"[{self.worker_id}] Ошибка при закрытии MSS: {e}")
                self.sct = None

            # easyocr reader передается извне, его здесь не удаляем/закрываем.
            self.ocr_reader = None # Очищаем ссылку

            logger.info(f"[{self.worker_id}] Очистка ресурсов Worker'а завершена.")
            logger.info(f"[{self.worker_id}] Worker завершил работу. Отправка finished({self.all_targets_reached}).")
            # Отправляем сигнал finished в основной поток
            self.finished.emit(self.all_targets_reached)

    def _sleep_interruptible(self, duration_sec: float) -> bool:
        """
        Выполняет паузу, которая может быть прервана флагом остановки Worker'а.
        Возвращает True, если пауза завершилась без прерывания, False если была прервана.
        """
        if not self._is_running: return False # Если уже запрошена остановка, не спим
        if duration_sec <= 0: return True # Пауза 0 или меньше - мгновенно, не прерываема

        # Ожидаем события остановки, но с таймаутом duration_sec
        interrupted = self._stop_event.wait(timeout=duration_sec)

        # interrupted == True, если событие было установлено в течение таймаута
        # interrupted == False, если таймаут истек
        # Возвращаем True, если пауза завершилась БЕЗ прерывания, и Worker still should be running
        return not interrupted and self._is_running


    def _try_refresh_list(self):
        """
        Пытается кликнуть по координатам кнопки 'Обновить'.
        Проверяет флаг остановки перед выполнением действий pyautogui.
        """
        # Проверяем, заданы ли координаты кнопки Обновить
        if REFRESH_BUTTON_X is None or REFRESH_BUTTON_Y is None:
            # logger.debug(f"[{self.worker_id}] Координаты кнопки Обновить не заданы. Пропуск обновления.")
            return # Нечего делать, если координаты не заданы

        # Проверяем флаг остановки перед началом действия
        if not self._is_running:
            logger.info(f"[{self.worker_id}] Обновление отменено, запрошена остановка.")
            return

        try:
            # Используем глобальную блокировку для pyautogui
            with input_lock:
                if not self._is_running:
                    return # Повторная проверка после получения блокировки
                logger.info(f"[{self.worker_id}] Клик по кнопке 'Обновить' ({REFRESH_BUTTON_X},{REFRESH_BUTTON_Y}).")
                pyautogui.click(REFRESH_BUTTON_X, REFRESH_BUTTON_Y)
                if not self._is_running:
                    return # Повторная проверка после клика

            # Обновляем время последнего обновления только при успешном клике
            self.last_refresh_time = time.monotonic()

        except pyautogui.FailSafeException:
             # pyautogui.FailSafeException может возникнуть, если курсор мыши
             # перемещен в угол экрана (защита pyautogui).
             logger.warning(f"[{self.worker_id}] pyAutoGUI FailSafe сработал при клике 'Обновить'. Пауза 1с.")
             # При FailSafe лучше остановиться или сделать большую паузу
             if not self._sleep_interruptible(1.0):
                 return # Проверка остановки после паузы

        except Exception:
            logger.exception(f"[{self.worker_id}] Ошибка при клике по кнопке 'Обновить':")
            # При ошибке клика делаем небольшую паузу
            if not self._sleep_interruptible(0.5):
                return


    def _find_and_check_price(
        self,
        item_bbox_global: dict, # Глобальные координаты bbox названия
        template_bbox_in_scan: tuple[int, int, int, int], # Коорд/размер bbox названия в scan_area
        item_data: dict,
        screen_bgr_scan_area: np.ndarray # BGR изображение области сканирования
    ) -> tuple[int | None, bool]:
        """
        Находит и распознает цену в области рядом с названием.
        Использует OCR с детализацией и фильтрацию блоков по положению и содержанию.
        """
        if not self._is_running: return None, False

        name = item_data.get("name", "N/A")
        target_price = item_data.get("max_price", DEFAULT_ITEM_MAX_PRICE)

        price = None
        price_ok = False
        price_search_roi_bgr = None # Область поиска цены для OCR

        try:
            # --- 1. Определяем область поиска цены ОТНОСИТЕЛЬНО НАЙДЕННОГО названия ---
            # Используем константу PRICE_SEARCH_RELATIVE_AREA = (X_OFFSET_REL, Y_OFFSET_REL, WIDTH, HEIGHT)
            rel_offset_x, rel_offset_y, search_width, search_height = PRICE_SEARCH_RELATIVE_AREA

            # Координаты верхнего левого угла НАЙДЕННОГО названия в scan_area
            template_x_in_scan, template_y_in_scan, template_w_in_scan, template_h_in_scan = template_bbox_in_scan

            # Координаты верхнего левого угла области поиска цены ВНУТРИ screen_bgr_scan_area
            # Смещение относительно ВЕРХНЕ-ЛЕВОГО угла НАЙДЕННОГО НАЗВАНИЯ
            price_search_x_in_scan = template_x_in_scan + rel_offset_x
            price_search_y_in_scan = template_y_in_scan + rel_offset_y


            # Размеры захваченного изображения области сканирования
            scan_h, scan_w = screen_bgr_scan_area.shape[:2]

            # Обрезаем область поиска по границам захваченной области сканирования
            roi_left = max(0, price_search_x_in_scan)
            roi_top = max(0, price_search_y_in_scan)

            # Координаты нижнего правого угла области поиска (до обрезки)
            price_search_right_in_scan = price_search_x_in_scan + search_width
            price_search_bottom_in_scan = price_search_y_in_scan + search_height

            roi_right = min(scan_w, price_search_right_in_scan)
            roi_bottom = min(scan_h, price_search_bottom_in_scan)

            # Проверяем валидность обрезанной области
            if roi_right <= roi_left or roi_bottom <= roi_top:
                logger.error(f"[{self.worker_id}] Расчетная область ПОИСКА цены для '{name}' невалидна после обрезки ({roi_left},{roi_top},{roi_right-roi_left},{roi_bottom-roi_top}).")
                # Отладочное сохранение даже пустой области, если DEBUG_SAVE_PRICE_ROI=True
                if DEBUG_SAVE_PRICE_ROI:
                     try:
                         dummy_img = np.zeros((10, 10, 3), dtype=np.uint8) # Маленькое черное изображение
                         cv2.imwrite(ABS_DEBUG_PRICE_ROI_PATH, dummy_img)
                         logger.info(f"[{self.worker_id}] [Цена '{name}'] Debug ROI (пустая область) сохранен: {ABS_DEBUG_PRICE_ROI_PATH}")
                     except Exception as e:
                         logger.error(f"[{self.worker_id}] Не удалось сохранить debug ROI (пустая область): {e}")
                return None, False

            # Вырезаем область поиска из захваченного BGR изображения области сканирования
            price_search_roi_bgr = screen_bgr_scan_area[roi_top:roi_bottom, roi_left:roi_right]

            # Повторная проверка на пустую область после вырезки
            if price_search_roi_bgr.size == 0:
                logger.warning(f"[{self.worker_id}] Пустая область ПОИСКА цены вырезана для '{name}'.")
                if DEBUG_SAVE_PRICE_ROI:
                     try:
                         dummy_img = np.zeros((10, 10, 3), dtype=np.uint8)
                         cv2.imwrite(ABS_DEBUG_PRICE_ROI_PATH, dummy_img)
                         logger.info(f"[{self.worker_id}] [Цена '{name}'] Debug ROI (пустая вырезка) сохранен: {ABS_DEBUG_PRICE_ROI_PATH}")
                     except Exception as e:
                         logger.error(f"[{self.worker_id}] Не удалось сохранить debug ROI (пустая вырезка): {e}")
                return None, False

            # --- Отладка: Сохранение ОБЛАСТИ ПОИСКА цены ---
            if DEBUG_SAVE_PRICE_ROI:
                try:
                    # Глобальные координаты верхнего левого угла области поиска цены
                    price_search_x_global = self.scan_area_coords["left"] + roi_left
                    price_search_y_global = self.scan_area_coords["top"] + roi_top
                    logger.info(
                        f"[{self.worker_id}] [Цена '{name}'] Debug ПОИСКОВАЯ область рассчитана: "
                        f"Глобальные ({price_search_x_global},{price_search_y_global}), "
                        f"Размер ({price_search_roi_bgr.shape[1]}x{price_search_roi_bgr.shape[0]})."
                    )
                    cv2.imwrite(ABS_DEBUG_PRICE_ROI_PATH, price_search_roi_bgr)
                    logger.info(f"[{self.worker_id}] [Цена '{name}'] Debug ПОИСКОВАЯ область сохранена: {ABS_DEBUG_PRICE_ROI_PATH}")
                except Exception as e:
                    logger.error(f"[{self.worker_id}] Не удалось сохранить debug ПОИСКОВУЮ область цены в {ABS_DEBUG_PRICE_ROI_PATH}: {e}")

        except Exception:
            logger.exception(f"[{self.worker_id}] Ошибка расчета/вырезки области ПОИСКА цены для '{name}':")
            return None, False

        # --- OCR: Распознавание текста в ОБЛАСТИ ПОИСКА цены (с детализацией) ---
        try:
            if not self._is_running:
                logger.info(f"[{self.worker_id}] Остановка Worker'а запрошена перед OCR области поиска цены для '{name}'.")
                return None, False

            logger.info(f"[{self.worker_id}] Запуск OCR на области ПОИСКА цены ({price_search_roi_bgr.shape[1]}x{price_search_roi_bgr.shape[0]}px, detail=1)...")
            # detail=1 возвращает (bbox, text, confidence)
            ocr_results_detail = self.ocr_reader.readtext(
                price_search_roi_bgr,
                allowlist=OCR_PRICE_ALLOWLIST,
                detail=1 # Получаем детализацию
            )
            logger.info(f"[{self.worker_id}] OCR области ПОИСКА завершен. Результатов: {len(ocr_results_detail)}")
            # Логируем все найденные блоки для отладки
            if ocr_results_detail:
                for i, (bbox, text, confidence) in enumerate(ocr_results_detail):
                    logger.debug(f"[{self.worker_id}]   OCR Block {i}: Text='{text}', Confidence={confidence:.2f}, Bbox={bbox}")


            if not self._is_running: return None, False

            best_price_candidate = None # (cleaned_text, confidence, bbox_in_search_roi)

            # --- 2. Ищем блок, похожий на цену, среди результатов OCR ---
            # Итерируем в обратном порядке, чтобы найти цену, которая обычно справа
            # Сортируем блоки по координате X верхнего левого угла (по убыванию)
            # Это позволяет обрабатывать блоки справа налево
            sorted_ocr_results = sorted(ocr_results_detail, key=lambda x: x[0][0][0], reverse=True)

            for (bbox_in_search_roi, text, confidence) in sorted_ocr_results:
                # Проверяем уверенность OCR для этого блока
                if confidence < PRICE_OCR_CONFIDENCE_THRESHOLD:
                   # logger.debug(f"[{self.worker_id}] Блок '{text}' имеет низкую уверенность {confidence:.2f}. Пропуск.")
                   continue # Пропускаем блоки с низкой уверенностью

                # Проверяем, похож ли текст блока на цену (содержит цифры и разрешенные символы)
                cleaned_text = self._extract_price_digits_only(text) # Используем доработанную логику для чистки и проверки *только* цифр
                if not cleaned_text:
                    # logger.debug(f"[{self.worker_id}] Блок '{text}' после чистки '{cleaned_text}' не содержит только цифр. Пропуск.")
                    continue # Пропускаем блоки, которые не являются чистыми числами

                # !!! Дополнительная проверка положения блока ОТНОСИТЕЛЬНО НАЙДЕННОГО НАЗВАНИЯ !!!
                # Координаты верхнего левого угла блока относительно *начала СКАНА*
                block_x_in_scan = roi_left + int(bbox_in_search_roi[0][0])
                block_y_in_scan = roi_top + int(bbox_in_search_roi[0][1])
                # Координаты нижнего правого угла блока относительно *начала СКАНА*
                # block_right_in_scan = roi_left + int(bbox_in_search_roi[2][0])
                # block_bottom_in_scan = roi_top + int(bbox_in_search_roi[2][1])

                # Проверяем горизонтальное положение: Левый край блока цены должен быть правее
                # левого края названия + минимальный отступ.
                if block_x_in_scan < template_x_in_scan + PRICE_MIN_HORIZONTAL_OFFSET_FROM_TEMPLATE_LEFT:
                    # logger.debug(f"[{self.worker_id}] Блок '{text}' (X={block_x_in_scan}) находится слишком ЛЕВЕЕ ({template_x_in_scan + PRICE_MIN_HORIZONTAL_OFFSET_FROM_TEMPLATE_LEFT}) названия. Пропуск.")
                    continue # Блок слишком далеко слева

                # Проверяем вертикальное положение: Верхний край блока цены должен находиться
                # в заданном диапазоне относительно НИЖНЕГО края названия.
                template_bottom_y_in_scan = template_y_in_scan + template_h_in_scan

                if not (block_y_in_scan >= template_bottom_y_in_scan + PRICE_MIN_VERTICAL_OFFSET_FROM_TEMPLATE_BOTTOM and
                        block_y_in_scan <= template_bottom_y_in_scan + PRICE_MAX_VERTICAL_OFFSET_FROM_TEMPLATE_BOTTOM):
                     # logger.debug(f"[{self.worker_id}] Блок '{text}' (Y={block_y_in_scan}) находится вне ожидаемого вертикального диапазона ({template_bottom_y_in_scan + PRICE_MIN_VERTICAL_OFFSET_FROM_TEMPLATE_BOTTOM}-{template_bottom_y_in_scan + PRICE_MAX_VERTICAL_OFFSET_FROM_TEMPLATE_BOTTOM}) относительно низа названия. Пропуск.")
                     continue # Блок не на ожидаемой строке цены


                # Если блок прошел все проверки (уверенность, текст, положение)
                # Считаем его валидным кандидатом. Так как мы итерируем справа налево,
                # первый найденный валидный блок, вероятно, и есть цена.
                # Выбираем этот блок как лучший и останавливаем поиск кандидатов.
                best_price_candidate = (cleaned_text, confidence, bbox_in_search_roi)
                logger.debug(f"[{self.worker_id}] Найден первый подходящий кандидат цены (справа): '{cleaned_text}' with confidence {confidence:.2f}")
                break # Выходим из цикла поиска кандидатов


            # --- 3. Если кандидат на цену найден ---
            if best_price_candidate:
                price_str, confidence, bbox_in_search_roi = best_price_candidate
                logger.info(f"[{self.worker_id}] [Цена '{name}'] Выбран лучший кандидат: '{price_str}' with confidence {confidence:.2f}")

                try:
                    price = int(price_str)
                    logger.info(f"[{self.worker_id}] [Цена '{name}'] Конвертировано в int: {price}$.")
                    price_ok = (target_price <= 0) or (price <= target_price)

                    if target_price > 0:
                         log_check = f"({price}$ <= {target_price}$)"
                         logger.info(f"[{self.worker_id}] [Цена '{name}'] Условие цены ({target_price}$): {log_check} -> {price_ok}")
                    else:
                         logger.info(f"[{self.worker_id}] [Цена '{name}'] Условие цены (Любая): Всегда True -> {price_ok}")

                    if not price_ok and target_price > 0:
                         logger.info(f"[{self.worker_id}] Цена ВЫШЕ лимита для '{name}': {price}$ > {target_price}$.")

                    return price, price_ok # Возвращаем найденную цену и результат проверки

                except ValueError:
                    logger.error(f"[{self.worker_id}] Ошибка конвертации лучшего кандидата '{price_str}' в int для '{name}'.")
                    return None, False

            else:
                # Ни один блок не прошел проверку на кандидата цены
                logger.warning(f"[{self.worker_id}] Не найдено блоков, похожих на цену и соответствующих положению, в области поиска для '{name}'.")
                # Опционально можно логировать все результаты OCR здесь, если не логируются выше
                # logger.debug(f"[{self.worker_id}] Все OCR результаты в области поиска: {ocr_results_detail}")
                return None, False

        except Exception:
            logger.exception(f"[{self.worker_id}] Неожиданная ошибка при OCR/поиске блока цены для '{name}':")
            return None, False

    # Новая версия функции для извлечения *только* цифр и проверки, что нет других символов
    def _extract_price_digits_only(self, text: str) -> str:
        """
        Очищает строку от разрешенных нецифровых символов ($, пробелы, запятые)
        и возвращает строку цифр, только если после чистки остаются ТОЛЬКО цифры.
        Возвращает пустую строку, если есть другие символы.
        """
        if not isinstance(text, str):
            return ""

        # Удаляем только разрешенные нецифровые символы
        cleaned_text = text.strip().replace("$", "").replace(" ", "").replace(",", "")

        # Проверяем, что после удаления разрешенных символов осталась строка, состоящая ТОЛЬКО из цифр
        if cleaned_text.isdigit():
            return cleaned_text
        else:
            return "" # Возвращаем пустую строку, если были другие символы или пусто


    def _perform_item_action(
        self,
        item_bbox_global: dict, # Глобальные координаты bbox найденного шаблона
        item_data: dict, # Данные товара
        price: int # Распознанная цена
    ) -> bool:
        """
        Выполняет действие: клик левой кнопкой мыши по центру найденного элемента,
        затем нажатие клавиши Esc.
        Обновляет прогресс товара и отправляет сигнал.

        Возвращает True, если действие выполнено успешно до конца, False иначе
        (например, если Worker остановлен во время выполнения действия).
        """
        if not self._is_running:
            logger.warning(f"[{self.worker_id}] Действие для '{item_data.get('name','N/A')}' отменено, запрошена остановка.")
            return False # Не выполняем действие, если Worker останавливается

        name = item_data.get("name", "N/A")
        prog = self.item_progress.get(name)

        # Проверка, что прогресс отслеживается и цель еще не достигнута
        if not prog or prog["bought"] >= prog["target"]:
            logger.warning(f"[{self.worker_id}] Действие для '{name}' отменено: прогресс не отслеживается или цель уже достигнута.")
            return False

        try:
            # Рассчитываем центр найденного bounding box'а шаблона (глобальные координаты)
            center_x = item_bbox_global["left"] + item_bbox_global["width"] // 2
            center_y = item_bbox_global["top"] + item_bbox_global["height"] // 2

            # Опционально: Проверка, что координаты центра находятся в пределах экрана
            # (pyautogui может работать и с координатами вне экрана, но это хорошая проверка)
            # w_scr, h_scr = pyautogui.size() # Получение размера экрана может быть медленным
            # if not (0 <= center_x < w_scr and 0 <= center_y < h_scr):
            #     logger.error(f"[{self.worker_id}] Рассчитанные координаты ЦЕНТРА ({center_x},{center_y}) для '{name}' вне пределов экрана. Пропуск действия.")
            #     return False

        except Exception:
            logger.exception(f"[{self.worker_id}] Ошибка расчета центра для действия с '{name}':")
            return False # Ошибка при расчете координат

        try:
            # Текущее количество до действия
            current_bought = prog["bought"]
            # Количество после успешного действия
            next_bought_count = current_bought + 1
            target_qty = prog["target"]

            log_msg = (
                f"[{self.worker_id}] !!! ВЫПОЛНЯЕТСЯ ДЕЙСТВИЕ для '{name}': "
                f"Клик ЛКМ ({center_x},{center_y}) + Нажатие ESC. "
                f"Цена: {price}$. Прогресс: {next_bought_count}/{target_qty}"
            )
            logger.info(log_msg)

            # --- Выполнение клика и Esc с блокировкой ---
            # Используем input_lock, чтобы другие потоки (если появятся)
            # не пытались использовать pyautogui одновременно.
            with input_lock:
                # Проверка остановки ПЕРЕД кликом
                if not self._is_running:
                    logger.warning(f"[{self.worker_id}] Действие (Клик) для '{name}' отменено перед pyautogui.click, запрошена остановка.")
                    return False

                # Выполняем клик
                # TODO: Проверить, может ли pyautogui.click быть прерван? Скорее всего, нет.
                pyautogui.click(center_x, center_y)

                # Проверка остановки ПОСЛЕ клика, ПЕРЕД Esc
                if not self._is_running:
                    logger.warning(f"[{self.worker_id}] Действие (Esc) для '{name}' отменено перед pyautogui.press('esc'), запрошена остановка.")
                    return False

                # Короткая пауза между кликом и Esc может быть полезна
                # time.sleep(0.05)
                # Проверка остановки ПОСЛЕ короткой паузы (если она есть)
                if not self._is_running:
                    logger.warning(f"[{self.worker_id}] Действие (Esc) для '{name}' отменено после паузы, запрошена остановка.")
                    return False

                # Выполняем нажатие Esc
                # TODO: Проверить, может ли pyautogui.press быть прерван? Скорее всего, нет.
                pyautogui.press("esc")

                # Проверка остановки ПОСЛЕ Esc
                if not self._is_running:
                    logger.warning(f"[{self.worker_id}] Действие для '{name}' прервано после pyautogui.press('esc'), запрошена остановка.")
                    return False

            # Если мы дошли до этого места, значит клик и Esc были успешно вызваны (не обязательно выполнены игрой!)
            # Обновляем счетчик купленного в прогрессе Worker'а
            prog["bought"] = next_bought_count
            logger.info(f"[{self.worker_id}] Прогресс для '{name}' обновлен: {prog['bought']}/{prog['target']}")

            # Отправляем сигнал в основной поток об успешном действии
            # Этот сигнал будет обработан в MainThread для обновления UI и звукового оповещения
            self.action_performed_signal.emit(name, price, prog["bought"])
            logger.info(f"[{self.worker_id}] Сигнал action_performed_signal({name}, {price}, {prog['bought']}) отправлен.")

            return True # Действие успешно инициировано и прогресс обновлен

        except pyautogui.FailSafeException:
             logger.warning(f"[{self.worker_id}] pyAutoGUI FailSafe сработал при выполнении действия для '{name}'. Пауза 1с.")
             # При FailSafe лучше остановиться или сделать большую паузу
             if not self._sleep_interruptible(1.0):
                 return False # Проверка остановки после паузы
             return False # Действие не было завершено корректно

        except Exception:
            # Логируем любую другую ошибку при выполнении действий pyautogui
            logger.exception(f"[{self.worker_id}] Ошибка при выполнении действий (Клик+ESC) для '{name}':")
            # При ошибке действия возвращаем False
            return False

    @pyqtSlot()
    def stop(self):
        """
        Устанавливает флаг остановки Worker'а и запрашивает прерывание
        потока Qt. Вызывается из основного потока.
        """
        # Проверяем, не установлен ли флаг уже
        if not self._stop_event.is_set():
            logger.info(f"[{threading.current_thread().name}] Worker.stop() вызван. Установка флага остановки и запрос прерывания потока...")
            # Устанавливаем наше событие, которое используется в _sleep_interruptible
            self._stop_event.set()

            # Запрашиваем прерывание потока Qt.
            # Это работает в сочетании с self._is_running, т.к. _is_running проверяет этот флаг.
            qt_thread = QtCore.QThread.currentThread()
            if qt_thread:
                 # Убедимся, что мы не запрашиваем прерывание основного потока QApplication
                 # Worker всегда должен выполняться в отдельном потоке.
                 # Проверяем имя потока, чтобы исключить MainThread
                 # Worker Thread ID должен быть отличен от MainThread ID
                 if threading.current_thread().ident != qt_thread.ident: # Проверка на всякий случай
                     if not qt_thread.isInterruptionRequested():
                         qt_thread.requestInterruption()
                         logger.info(f"[{threading.current_thread().name}] Запрос прерывания для QThread '{qt_thread.objectName() or 'N/A'}' отправлен.")
                     else:
                         logger.info(f"[{threading.current_thread().name}] QThread '{qt_thread.objectName() or 'N/A'}' уже имеет запрос на прерывание.")
                 else:
                     logger.error(f"[{threading.current_thread().name}] Попытка запросить прерывание для своего потока Worker!")
            else:
                 logger.warning(f"[{threading.current_thread().name}] Не удалось получить ссылку на QThread для запроса прерывания.")
        else:
             logger.info(f"[{threading.current_thread().name}] Worker.stop() вызван, но флаг остановки уже установлен.")


# ============================================================================
# === Класс BotLogic: Управление логикой приложения ===
# ============================================================================
# BotLogic наследуется от QObject для возможности использования сигналов/слотов
# и перемещения в другой поток, если потребуется (хотя Worker в отдельном потоке).
class BotLogic(QObject):
    """
    Основной класс управляющей логики приложения.
    Отвечает за состояние приложения, загрузку/сохранение данных,
    взаимодействие с GUI, инициализацию ресурсов (MSS, OCR),
    управление фоновым Worker-потоком и глобальные хоткеи.
    """

    # Сигналы для взаимодействия с GUI (MainWindow)
    signal_update_status = pyqtSignal(str) # Обновить строку статуса
    signal_enable_controls = pyqtSignal(bool) # Включить/выключить элементы управления GUI
    signal_update_item_list = pyqtSignal(list) # Обновить список товаров в GUI
    signal_action_performed = pyqtSignal(str, int, int) # name, price, total_bought (из Worker)
    signal_monitoring_stopped = pyqtSignal(bool) # bool: True если остановлен по достижению цели (из Worker)
    # signal_init_error = pyqtSignal(str) # Сигнал об ошибке инициализации (оционально)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Устанавливаем имя основного потока для логов
        threading.current_thread().name = "MainThread"
        logger.info("Инициализация BotLogic...")

        # Состояние приложения
        self.monitoring_active = False
        self.is_selecting_area = False

        # Настройки
        self.ignore_rent = False # Игнорировать ли товары с названием "Аренда" (из constants или загружается)

        # Данные о товарах
        # Список словарей, каждый словарь описывает один товар (name, enabled, max_price, quantity, template_path, bought_count)
        self.item_data_list = []

        # Ресурсы (инициализируются при запуске BotLogic)
        self.m_sct = None # MSS скриншоттер (основной экземпляр для выделения области)
        self.m_ocr_reader = None # EasyOCR Reader (основной экземпляр)
        self.m_screen_selector = None # Виджет для выделения области

        # Поток и Worker для фоновой работы
        self.m_worker = None
        self.m_thread = None

        # Флаг успешной инициализации BotLogic
        self.initialized_ok = False
        # Флаг для отслеживания вызова cleanup
        self.cleanup_called = False

        # Сохраняем BASE_DIR как атрибут класса для удобства доступа из других методов
        self.BASE_DIR = BASE_DIR

        # --- Инициализация ресурсов ---
        # Если инициализация не удалась, initialized_ok останется False,
        # и Main.py должен проверить это и завершить работу.
        self.initialized_ok = self._init_resources()

        if self.initialized_ok:
            # Загрузка данных о товарах (если успешно инициализированы ресурсы)
            self._load_item_data()
            # Настройка глобальных горячих клавиш
            self._setup_global_hotkey()
            logger.info("Инициализация BotLogic завершена успешно.")
            # Установка статуса "Готов" после успешной инициализации
            self.signal_update_status.emit("Готов.")
        else:
            logger.critical("Инициализация BotLogic завершилась с ошибками.")
            # Уведомление пользователя об ошибке инициализации произойдет в main.py
            # после проверки self.initialized_ok
            pass # Инициализация не удалась, Main.py обработает выход

    def _quit_application(self):
        """Вызывает выход из приложения PyQt."""
        logger.info("Запрос на выход из приложения PyQt...")
        # QApplication.quit() безопаснее sys.exit() в контексте Qt
        QApplication.quit()


    # --- Методы инициализации и настройки ---
    def _init_resources(self) -> bool:
        """
        Инициализирует основные ресурсы приложения: папку шаблонов, MSS, EasyOCR.
        Возвращает True при успехе, False при ошибке.
        """
        logger.info("--- Инициализация основных ресурсов ---")
        all_ok = True # Флаг общего успеха

        # 1. Создание папки шаблонов
        if not self._create_template_folder():
            logger.warning("Не удалось создать папку шаблонов. Функционал добавления/хранения шаблонов может быть ограничен.")
            # Продолжаем, это не критическая ошибка для всего приложения

        # 2. Инициализация MSS (для захвата экрана в режиме выделения области)
        if self.m_sct is None:
            try:
                self.m_sct = mss.mss()
                logger.info("MSS инициализирован.")
            except Exception:
                logger.exception("КРИТИЧЕСКАЯ ОШИБКА инициализации MSS:")
                # Отправляем сигнал об ошибке в UI после инициализации UI
                # self.signal_update_status.emit("Ошибка MSS!")
                all_ok = False # Критическая ошибка

        # 3. Инициализация EasyOCR Reader
        # OCR Reader создается один раз в основном потоке и передается Worker'у.
        # EasyOCR с gpu=False должен быть потокобезопасным или допускать использование
        # одного инстанса из нескольких потоков последовательно.
        if self.m_ocr_reader is None and all_ok: # Инициализируем OCR только если MSS инициализирован успешно
            try:
                logger.info(f"Попытка инициализации EasyOCR с языками: {OCR_LANGUAGES}, gpu=False")
                self.m_ocr_reader = easyocr.Reader(OCR_LANGUAGES, gpu=False)
                logger.info("EasyOCR инициализирован.")

                # Прогрев OCR: выполняем тестовое распознавание на пустом изображении
                # Это может помочь загрузить модели и ускорить первое реальное распознавание.
                logger.info("Прогрев OCR...")
                try:
                    # Создаем маленькое пустое изображение
                    dummy_img = np.zeros((50, 200, 3), dtype=np.uint8)
                    _ = self.m_ocr_reader.readtext(dummy_img, detail=0)
                    logger.info("Прогрев OCR завершен успешно.")
                except Exception as warm_e:
                     logger.warning(f"Ошибка при прогреве OCR: {warm_e}")

                # Статус "OCR готов" будет установлен в UI после инициализации Logic
                # и создания MainWindow, через сигнал signal_update_status
                # self.signal_update_status.emit(f"OCR готов ({', '.join(OCR_LANGUAGES)}).")


            except Exception:
                logger.exception("КРИТИЧЕСКАЯ ОШИБКА инициализации EasyOCR:")
                # Отправляем сигнал об ошибке в UI после инициализации UI
                # self.signal_update_status.emit("Ошибка OCR!")
                all_ok = False # Критическая ошибка

        # Общий результат инициализации
        if not all_ok:
            logger.error("--- Инициализация ресурсов ЗАВЕРШИЛАСЬ С ОШИБКАМИ! ---")
            # При ошибках инициализации, возможно, нужно освободить то, что успели занять
            self.cleanup() # Пытаемся очистить ресурсы
            # Уведомление пользователя об ошибке инициализации произойдет в main.py
            # после проверки self.initialized_ok
        else:
            logger.info("--- Все необходимые ресурсы успешно инициализированы ---")

        return all_ok # Возвращаем общий результат

    def _create_template_folder(self) -> bool:
        """Создает папку для сохранения шаблонов, если она не существует."""
        if not os.path.exists(ABS_TEMPLATE_FOLDER):
            logger.info(f"Создание папки шаблонов: {ABS_TEMPLATE_FOLDER}")
            try:
                os.makedirs(ABS_TEMPLATE_FOLDER)
                return True
            except OSError:
                # Логируем ошибку создания папки
                logger.exception(f"Ошибка создания папки '{ABS_TEMPLATE_FOLDER}':")
                # Отправляем сигнал в UI после инициализации UI
                # self.signal_update_status.emit("Ошибка папки шаблонов!");
                return False # Не удалось создать папку
        return True # Папка уже существует или успешно создана

    def _setup_global_hotkey(self):
        """Настраивает глобальные горячие клавиши для добавления/остановки."""
        logger.info("--- Настройка глобальных горячих клавиш ---")
        try:
            # Проверка, доступна ли библиотека keyboard
            if "keyboard" not in sys.modules:
                raise ImportError("Модуль 'keyboard' не импортирован.")

            # Попытка удаления предыдущих хоткеев (если скрипт перезапускается без полного выхода процесса)
            # Ошибки KeyError/AttributeError игнорируются, если хоткеи не были зарегистрированы
            try:
                keyboard.remove_hotkey(ADD_ITEM_HOTKEY)
                logger.debug(f"Удален старый хоткей '{ADD_ITEM_HOTKEY.upper()}'.")
            except (KeyError, AttributeError):
                pass
            try:
                keyboard.remove_hotkey(STOP_MONITORING_HOTKEY)
                logger.debug(f"Удален старый хоткей '{STOP_MONITORING_HOTKEY}'.")
            except (KeyError, AttributeError):
                pass

            # Регистрация новых хоткеев
            # trigger_on_release=True позволяет избежать многократного срабатывания при долгом нажатии
            keyboard.add_hotkey(ADD_ITEM_HOTKEY, self._safe_trigger_area_selection, trigger_on_release=True)
            logger.info(f"Глобальный хоткей '{ADD_ITEM_HOTKEY.upper()}' [Добавить товар] зарегистрирован.")

            keyboard.add_hotkey(STOP_MONITORING_HOTKEY, self._safe_stop_monitoring, trigger_on_release=True)
            logger.info(f"Глобальный хоткей '{STOP_MONITORING_HOTKEY}' [Стоп поиск] зарегистрирован.")

            logger.warning("!!! Глобальные хоткеи могут требовать прав администратора для работы вне окна приложения !!!")

        except ImportError:
            logger.warning("Библиотека 'keyboard' не найдена. Глобальные хоткеи отключены.")
            self.signal_update_status.emit("Хоткеи отключены!")
        except Exception:
            # Логируем любую другую ошибку при настройке хоткеев
            logger.exception("Ошибка настройки глобальных хоткеев:")
            msg = "Ошибка хоткеев (требуются права админа?)"
            self.signal_update_status.emit(msg)


    # --- Безопасные слоты для вызова из потока хоткеев ---
    # Методы, вызываемые глобальными хоткеями (которые работают в своем потоке),
    # должны безопасно взаимодействовать с объектами Qt в основном потоке (GUI).
    # Используем QMetaObject.invokeMethod с QueuedConnection.
    def _safe_trigger_area_selection(self):
        """Безопасно вызывает trigger_area_selection в потоке QApplication."""
        # Проверяем, что QApplication существует и не завершается
        if QApplication.instance() and not QApplication.instance().closingDown():
             QMetaObject.invokeMethod(
                 self,
                 "trigger_area_selection",
                 Qt.ConnectionType.QueuedConnection # Обязательно QueuedConnection
             )
        else:
             logger.warning("[Hotkey] Не удалось вызвать trigger_area_selection: QApplication недоступен.")

    def _safe_stop_monitoring(self):
        """Безопасно вызывает stop_monitoring в потоке QApplication."""
        if QApplication.instance() and not QApplication.instance().closingDown():
             QMetaObject.invokeMethod(
                 self,
                 "stop_monitoring",
                 Qt.ConnectionType.QueuedConnection # Обязательно QueuedConnection
             )
        else:
             logger.warning("[Hotkey] Не удалось вызвать stop_monitoring: QApplication недоступен.")


    # --- Методы работы с данными товаров ---
    def _sanitize_filename(self, name: str) -> str:
        """
        Очищает строку имени для использования в качестве имени файла.
        Удаляет недопустимые символы, заменяет пробелы и некоторые символы на
        подчеркивания, выполняет транслитерацию кириллицы (если библиотека доступна).
        Ограничивает длину имени файла.
        """
        if not name: return "unnamed_item" # Имя не может быть пустым

        # Удаляем символы, недопустимые в именах файлов большинства ОС
        # <>:"/\\|?* и управляющие символы (\x00-\x1f)
        sanitized_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name))

        # Транслитерация кириллицы, если доступна библиотека и имя содержит кириллицу
        if TRANS_AVAILABLE and any('\u0400' <= c <= '\u04FF' for c in sanitized_name):
             try:
                 # Попытка транслитерации из русского
                 transliterated_name = translit(sanitized_name, "ru", reversed=True)
                 # Если транслитерация успешна и не пуста, используем ее
                 if transliterated_name:
                     sanitized_name = transliterated_name
                 else:
                     logger.warning(f"Транслитерация имени файла '{name}' дала пустой результат.")
             except Exception:
                 # Логируем ошибку транслитерации, но продолжаем с не-транслитерированным именем
                 logger.exception(f"Ошибка при транслитерации имени файла '{name}':")

        # Заменяем последовательности пробелов и подчеркиваний на одно подчеркивание
        sanitized_name = re.sub(r"[\s_]+", "_", sanitized_name)

        # Удаляем подчеркивания в начале и конце имени файла
        sanitized_name = sanitized_name.strip("._")

        # Если после всех очисток имя стало пустым, используем фоллбэк
        if not sanitized_name:
             sanitized_name = "invalid_item_name"

        # Обрезаем имя файла до разумной длины
        MAX_FILENAME_LENGTH = 100 # Максимальная длина имени (без расширения)
        if len(sanitized_name) > MAX_FILENAME_LENGTH:
            sanitized_name = sanitized_name[:MAX_FILENAME_LENGTH]
            logger.warning(f"Имя файла обрезано до {MAX_FILENAME_LENGTH} символов.")

        return sanitized_name


    def _load_item_data(self):
        """Загружает данные о товарах из JSON файла."""
        fname = os.path.basename(ABS_ITEM_DATA_FILE)
        logger.info(f"Загрузка данных о товарах из файла: {ABS_ITEM_DATA_FILE}")

        # Если файл не существует, инициализируем пустой список и выходим
        if not os.path.exists(ABS_ITEM_DATA_FILE):
            logger.warning(f"Файл данных '{fname}' не найден. Создан пустой список товаров.")
            self.item_data_list = []
            # Обновляем UI (список будет пустым)
            self.signal_update_item_list.emit(self.get_item_data_for_display())
            return

        try:
            # Чтение файла
            with open(ABS_ITEM_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Проверка формата: ожидаем список словарей
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise TypeError("Некорректный формат данных в файле.")

            self.item_data_list = data
            n = len(data)
            logger.info(f"Успешно загружены данные для {n} товаров из '{fname}'.")

            # Валидация и исправление путей к шаблонам (если они относительные)
            # Это важно, если приложение перемещается
            if self._validate_and_fix_paths():
                 logger.info("Пути к шаблонам исправлены. Пересохраняем файл данных.")
                 self._save_item_data() # Сохраняем исправленные данные

            # Инициализируем счетчик "куплено" для каждого товара при загрузке
            # (Счетчик сбрасывается при каждом запуске приложения)
            for item in self.item_data_list:
                 item['bought_count'] = 0 # Добавляем или сбрасываем счетчик

            # Обновляем UI список товаров
            self.signal_update_item_list.emit(self.get_item_data_for_display())

        except (json.JSONDecodeError, TypeError) as err:
            # Ошибка парсинга JSON или некорректный формат данных
            msg = f"КРИТИЧЕСКАЯ ОШИБКА загрузки данных из '{fname}': {err}. Список товаров будет очищен."
            logger.error(msg)
            # Очищаем список товаров в памяти
            self.item_data_list = []
            self.signal_update_item_list.emit([]) # Обновляем UI (список пуст)

            # Попытка сделать резервную копию поврежденного файла
            backup_path = ABS_ITEM_DATA_FILE + ".corrupted_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                if os.path.exists(ABS_ITEM_DATA_FILE):
                    os.rename(ABS_ITEM_DATA_FILE, backup_path)
                    logger.warning(f"Поврежденный файл данных сохранен как: {os.path.basename(backup_path)}")
                    backup_msg = f"Поврежденный файл сохранен как: {os.path.basename(backup_path)}"
                else:
                    backup_msg = "Оригинальный файл не найден для резервной копии."
            except OSError as e:
                logger.error(f"Не удалось создать резервную копию файла '{fname}': {e}")
                backup_msg = f"Не удалось создать резервную копию файла: {e}"

            # Показываем сообщение пользователю
            QMessageBox.critical(
                None,
                "Ошибка загрузки данных",
                f"Не удалось загрузить данные о товарах из файла '{fname}':\n{err}\n\n"
                f"{backup_msg}\n\nСписок товаров был очищен."
            )

        except Exception as e:
            # Ловим любые другие неожиданные ошибки при загрузке
            logger.exception("Неожиданная ошибка при загрузке данных:")
            self.item_data_list = [] # Очищаем список
            self.signal_update_item_list.emit([]) # Обновляем UI
            QMessageBox.critical(None, "Ошибка загрузки данных", f"Произошла неожиданная ошибка при загрузке данных:\n{e}\n\nСписок товаров был очищен.")


    def _validate_and_fix_paths(self) -> bool:
        """
        Проверяет пути к шаблонам в загруженных данных. Если путь относительный,
        конвертирует его в абсолютный, используя BASE_DIR.
        Возвращает True, если были внесены исправления, требующие пересохранения.
        """
        needs_resave = False # Флаг, были ли изменения
        for item in self.item_data_list:
            path = item.get("template_path")
            name = item.get("name", "N/A")
            # Проверяем, что путь существует и является строкой
            if not path or not isinstance(path, str):
                # logger.warning(f"Для товара '{name}' отсутствует или некорректен путь к шаблону.")
                continue # Пропускаем элемент без пути

            # Проверяем, является ли путь абсолютным
            if not os.path.isabs(path):
                # Если путь относительный, делаем его абсолютным относительно BASE_DIR
                abs_path = os.path.abspath(os.path.join(BASE_DIR, path))
                logger.info(f"Исправление относительного пути для '{name}': '{path}' -> '{abs_path}'.")
                item["template_path"] = abs_path # Обновляем путь в данных
                needs_resave = True # Нужно пересохранить

            # Можно добавить проверку существования файла здесь, но это уже
            # делается в Worker'е и _get_enabled_items_with_templates

        return needs_resave # Возвращаем True, если были исправления

    def _save_item_data(self):
        """Сохраняет текущие данные о товарах в JSON файл с использованием временного файла."""
        temp_path = ABS_ITEM_DATA_FILE + ".tmp"
        fname = os.path.basename(ABS_ITEM_DATA_FILE)
        logger.info(f"Сохранение данных о товарах в файл: {ABS_ITEM_DATA_FILE}")
        try:
            # Сериализуем список в JSON в временный файл
            with open(temp_path, "w", encoding="utf-8") as f:
                # ensure_ascii=False для корректного сохранения кириллицы и других символов
                # indent=4 для красивого форматирования JSON
                json.dump(self.item_data_list, f, ensure_ascii=False, indent=4)

            # Атомарно заменяем старый файл новым временным
            # Это предотвращает потерю данных при сбое во время записи
            os.replace(temp_path, ABS_ITEM_DATA_FILE)
            logger.info(f"Данные успешно сохранены в '{fname}'.")

        except Exception:
            # Логируем ошибку сохранения
            logger.exception(f"КРИТИЧЕСКАЯ ОШИБКА сохранения данных в '{fname}':")
            self.signal_update_status.emit("Ошибка сохранения данных!") # Сигнал в UI

        finally:
            # Убеждаемся, что временный файл удален, даже если произошла ошибка
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    # logger.debug(f"Временный файл {temp_path} удален.")
                except OSError:
                    logger.error(f"Не удалось удалить временный файл {temp_path}.")


    def get_item_data_for_display(self) -> list:
        """Возвращает копию текущего списка данных о товарах для отображения в UI."""
        # Возвращаем копию, чтобы UI не мог случайно изменить оригинальный список
        return [item.copy() for item in self.item_data_list]

    def get_item_data_by_name(self, name: str) -> dict | None:
        """Находит и возвращает словарь данных товара по его имени."""
        # Используем next() с генераторным выражением для эффективного поиска
        return next(
            (item for item in self.item_data_list if item.get("name") == name),
            None # Возвращаем None, если товар не найден
        )

    @pyqtSlot(int)
    def set_ignore_rent_state(self, state: int):
        """Слот для обновления состояния чекбокса "Игнорировать Аренда"."""
        # Аргумент state приходит от сигнала stateChanged чекбокса (0=Unchecked, 2=Checked)
        self.ignore_rent = (state == Qt.CheckState.Checked.value)
        logger.info(f"Настройка 'Игнорировать Аренда' изменена на: {'ВКЛ' if self.ignore_rent else 'ВЫКЛ'}.")
        # Сохранять эту настройку между сессиями можно было бы добавить сюда

    @pyqtSlot(str)
    def remove_item(self, name: str):
        """Слот для удаления товара по имени."""
        # Проверяем, не запущены ли процессы, блокирующие управление данными
        if self.monitoring_active or self.is_selecting_area:
            self.signal_update_status.emit("Сначала остановите процесс!");
            logger.warning(f"Попытка удалить товар '{name}' во время активного процесса.")
            return

        # Находим товар по имени
        item = self.get_item_data_by_name(name)
        if item:
            try:
                # Удаляем товар из списка в памяти
                self.item_data_list.remove(item)
                logger.info(f"Товар '{name}' удален из списка.")
                self.signal_update_status.emit(f"Удалено: {name[:30]}...") # Обновляем статус в UI

                # Попытка удаления связанного файла шаблона
                path = item.get("template_path")
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info(f"Файл шаблона удален: {path}")
                    except OSError as e:
                        logger.error(f"Ошибка удаления файла шаблона '{path}': {e}")
                    except Exception:
                         logger.exception(f"Неожиданная ошибка при удалении файла шаблона '{path}':")

                # Обновляем UI список
                self.signal_update_item_list.emit(self.get_item_data_for_display())
                # Сохраняем измененный список данных
                self._save_item_data()

            except Exception:
                logger.exception(f"Ошибка при удалении товара '{name}':")
                self.signal_update_status.emit(f"Ошибка при удалении товара: {name[:30]}...")

        else:
            logger.error(f"Товар '{name}' не найден в списке для удаления.")
            # Можно уведомить пользователя, если товар не нашелся, хотя UI кнопку должен был заблокировать

    @pyqtSlot(str, dict)
    def update_item_data(self, name: str, data: dict):
        """Слот для обновления параметров товара по имени."""
         # Проверяем, не запущены ли процессы
        if self.monitoring_active or self.is_selecting_area:
            self.signal_update_status.emit("Сначала остановите процесс!");
            logger.warning(f"Попытка обновить товар '{name}' во время активного процесса.")
            return

        # Находим товар по имени
        item = self.get_item_data_by_name(name)
        if item:
            # Разрешаем обновлять только определенные поля
            allowed_keys = {"enabled", "max_price", "quantity"}
            # Создаем словарь с полями, которые разрешено обновлять и которые присутствуют в data
            payload = {k: data[k] for k in allowed_keys if k in data}

            # Обновляем поля в словаре товара в списке
            item.update(payload)

            logger.info(f"Данные для товара '{name}' обновлены: {payload}")
            self.signal_update_status.emit(f"Обновлено: {name[:30]}...") # Обновляем статус UI

            # Обновляем UI список товаров
            self.signal_update_item_list.emit(self.get_item_data_for_display())
            # Сохраняем измененный список данных
            self._save_item_data()

        else:
            logger.error(f"Товар '{name}' не найден в списке для обновления.")
            # Этого не должно происходить, если UI корректно передает имя

    @pyqtSlot(str, bool)
    def set_item_enabled_status(self, name: str, enabled: bool):
        """Слот для изменения статуса 'включен'/'выключен' для товара."""
        # Этот слот вызывается при изменении чекбокса в списке UI
        item = self.get_item_data_by_name(name)
        if item and item.get("enabled") != enabled:
            item["enabled"] = enabled # Обновляем статус в данных
            logger.info(f"Статус поиска для '{name}' изменен на: {'ВКЛ' if enabled else 'ВЫКЛ'}.")
            # Сохраняем данные после изменения статуса
            self._save_item_data()
            # UI уже обновил чекбокс, но _on_item_check_changed также вызывает _style_list_item
            # и signal_update_item_list.emit, так что синхронизация UI должна быть полной.


    # --- Методы управления выделением области ---
    @pyqtSlot()
    def trigger_area_selection(self):
        """
        Запускает режим выделения области на экране с помощью ScreenSelectionWidget.
        Вызывается при клике на кнопку "Добавить" или по горячей клавише.
        """
        logger.info("--- Запрос на запуск режима выделения области ---")
        # Проверяем текущее состояние приложения
        if self.monitoring_active:
            self.signal_update_status.emit("Сначала остановите поиск!");
            logger.warning("Попытка запустить выделение во время мониторинга.")
            return
        if self.is_selecting_area:
            logger.warning("Режим выделения уже активен.")
            return

        # Проверяем, инициализированы ли необходимые ресурсы
        if self.m_sct is None or self.m_ocr_reader is None:
            self.signal_update_status.emit("Ошибка ресурсов (MSS/OCR)!");
            logger.error("MSS или OCR не инициализированы, невозможно начать выделение.")
            QMessageBox.critical(None, "Ошибка", "Система не инициализирована корректно (MSS/OCR недоступны).")
            return

        # Устанавливаем флаг режима выделения
        self.is_selecting_area = True
        # Отправляем сигнал UI для блокировки других контролов
        self.signal_enable_controls.emit(False)
        self.signal_update_status.emit("РЕЖИМ ВЫДЕЛЕНИЯ: Выделите область названия товара (ESC для отмены)...")
        logger.info(">>> Вход в режим выделения области...")

        # Создаем или переиспользуем виджет выделения
        if self.m_screen_selector is None:
            logger.info("Создание нового ScreenSelectionWidget...")
            try:
                # Создаем виджет, передавая self как родителя (для правильного потока сигналов)
                self.m_screen_selector = ScreenSelectionWidget(self.parent()) # Используем родителя logic (MainWindow)
                # Подключаем сигналы виджета выделения к нашим слотам
                self.m_screen_selector.area_selected.connect(self._handle_area_selected)
                self.m_screen_selector.selection_cancelled.connect(self._handle_selection_cancelled)
                logger.info("ScreenSelectionWidget создан и сигналы подключены.")
            except Exception:
                # Логируем ошибку создания виджета
                logger.exception("КРИТИЧЕСКАЯ ошибка создания ScreenSelectionWidget:")
                self.is_selecting_area = False # Сбрасываем флаг
                self.signal_enable_controls.emit(True) # Разблокируем контролы
                self.signal_update_status.emit("Ошибка виджета выделения!");
                QMessageBox.critical(None, "Ошибка", "Не удалось создать виджет выделения области.")
                return

        # Показываем виджет на весь экран и поднимаем его на передний план
        self.m_screen_selector.showFullScreen()
        self.m_screen_selector.raise_() # Поднять на передний план

    @pyqtSlot(QRect)
    def _handle_area_selected(self, rect: QRect):
        """
        Слот, вызываемый ScreenSelectionWidget при успешном выделении области.
        Выполняет захват области, OCR, обработку результата и сохранение шаблона.
        """
        logger.info(f"Получен сигнал area_selected. Выделенная область (глобальные коорд): {rect.x()},{rect.y()},{rect.width()},{rect.height()}.")

        # Проверяем, что мы действительно в режиме выделения
        if not self.is_selecting_area:
            logger.warning("Получен сигнал area_selected, но режим выделения неактивен.")
            if self.m_screen_selector:
                self.m_screen_selector.hide() # Скрыть виджет на всякий случай
            return # Игнорируем сигнал, если флаг не установлен

        # Скрываем виджет выделения сразу, как только получили область
        if self.m_screen_selector:
             self.m_screen_selector.hide()
             # Опционально: небольшая пауза для отрисовки окон
             # time.sleep(0.1)

        # Обновляем статус в UI
        self.signal_update_status.emit("Обработка выделенной области...")
        # Обрабатываем события Qt, чтобы UI успел обновиться
        if QApplication.instance():
            QApplication.instance().processEvents()
        # time.sleep(0.1) # Короткая пауза может помочь

        name = None
        template_file_path = None
        captured_image_bgr = None # Переменные для сохранения результата

        try:
            # --- 1. Проверка и захват области экрана ---
            if not rect.isValid() or rect.width() < 5 or rect.height() < 5:
                 raise ValueError(f"Выделенная область слишком мала: {rect.width()}x{rect.height()}px.")

            # Координаты для захвата MSS
            coords_for_mss = {"top": rect.y(), "left": rect.x(), "width": rect.width(), "height": rect.height()}

            # Убедимся, что MSS доступен
            if not self.m_sct:
                 raise RuntimeError("MSS недоступен для захвата экрана.")

            logger.info(f"Захват области экрана MSS: {coords_for_mss}")
            grab = self.m_sct.grab(coords_for_mss)

            if not grab or grab.size[0] == 0 or grab.size[1] == 0:
                 raise ValueError("Не удалось захватить изображение выделенной области.")

            # Конвертация захваченного изображения в формат OpenCV (BGR)
            img_np = np.array(grab)
            if len(img_np.shape) == 3:
                if img_np.shape[2] == 4: # BGRA (например, с прозрачностью)
                    captured_image_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
                elif img_np.shape[2] == 3: # BGR (если нет альфа-канала)
                    captured_image_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR) # MSS захватывает как RGB
                else:
                     raise ValueError(f"Неподдерживаемое количество каналов изображения: {img_np.shape[2]}")
            elif len(img_np.shape) == 2: # Grayscale
                 captured_image_bgr = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
            else:
                 raise ValueError(f"Неподдерживаемый формат изображения из MSS: {img_np.shape}")

            if captured_image_bgr is None or captured_image_bgr.size == 0:
                 raise ValueError("Не удалось корректно конвертировать захваченное изображение.")


            # --- 2. Распознавание текста (OCR) ---
            # Убедимся, что OCR Reader доступен
            if not self.m_ocr_reader:
                 raise RuntimeError("EasyOCR Reader недоступен.")

            logger.info("Запуск OCR на захваченной области...")
            # Выполняем OCR на BGR изображении. detail=0 возвращает только текст.
            # paragraph=True пытается объединить текст в блоки (лучше для длинных названий).
            ocr_res = self.m_ocr_reader.readtext(captured_image_bgr, detail=0, paragraph=True)
            logger.info(f"OCR завершен. Результат: {ocr_res}")

            # Обработка результата OCR
            if not ocr_res:
                 raise ValueError("EasyOCR не распознал текст в выделенной области.")

            # Объединяем распознанные текстовые блоки в одну строку, очищаем лишние пробелы
            raw_text = " ".join(ocr_res)
            name = re.sub(r"\s+", " ", raw_text).strip() # Замена нескольких пробелов на один, удаление пробелов по краям

            # Финальная проверка, что имя не пустое после очистки
            if not name:
                 raise ValueError("OCR распознал пустой или некорректный текст после очистки.")

            logger.info(f"Распознанное название товара: '{name}'")

            # --- 3. Проверки (Игнорировать Аренда, Дубликаты) ---
            # Проверка настройки "Игнорировать Аренда"
            if self.ignore_rent and name.lower().startswith(("аренда", "rent")):
                msg = f"Добавление проигнорировано (название начинается с 'Аренда'/'Rent'): '{name[:40]}...'";
                logger.info(msg)
                self.signal_update_status.emit(msg)
                QMessageBox.information(None, "Проигнорировано", f"Товар '{name}' проигнорирован, так как включена настройка 'Игнор. Аренда'.");
                self._finalize_selection_mode(False); # Завершаем режим выделения без сохранения
                return # Выходим из метода

            # Проверка на дубликат (товар с таким именем уже есть)
            if self.get_item_data_by_name(name):
                msg = f"Товар с таким именем уже есть: '{name[:40]}...'";
                logger.warning(msg)
                self.signal_update_status.emit(msg)
                QMessageBox.information(None, "Дубликат товара", f"Товар с названием '{name}' уже существует в списке.");
                self._finalize_selection_mode(False); # Завершаем режим выделения без сохранения
                return # Выходим из метода

            # --- 4. Сохранение изображения как шаблона ---
            # Генерируем безопасное имя файла на основе названия товара
            sanitized_name = self._sanitize_filename(name)
            fname = f"{sanitized_name}.png"
            template_file_path = os.path.join(ABS_TEMPLATE_FOLDER, fname)

            # Проверка, существует ли файл (маловероятно после sanitize, но на всякий случай)
            if os.path.exists(template_file_path):
                logger.warning(f"Файл шаблона '{fname}' уже существует и будет перезаписан.")

            try:
                # Сохраняем BGR изображение захваченной области в файл PNG
                write_ok = cv2.imwrite(template_file_path, captured_image_bgr);
                if not write_ok:
                    raise IOError("cv2.imwrite вернул False, возможно, ошибка записи на диск или некорректный путь.")
                logger.info(f"Изображение шаблона успешно сохранено: {template_file_path}")
            except (cv2.error, IOError, OSError) as e:
                # Ошибка при сохранении файла
                # Проверяем, существует ли файл, который не удалось записать полностью, и пытаемся его удалить
                if os.path.exists(template_file_path):
                    try:
                        os.remove(template_file_path)
                        logger.warning("Удален частично записанный файл шаблона.")
                    except OSError:
                        pass # Игнорируем ошибку удаления
                raise IOError(f"Ошибка сохранения файла шаблона: {e}") # Пробрасываем ошибку дальше

            # --- 5. Добавление товара в список данных ---
            # Создаем новую запись для товара
            new_item_entry = {
                "name": name, # Распознанное имя
                "enabled": DEFAULT_ITEM_ENABLED, # Статус включен по умолчанию
                "max_price": DEFAULT_ITEM_MAX_PRICE, # Макс. цена по умолчанию
                "quantity": DEFAULT_ITEM_QUANTITY, # Целевое количество по умолчанию
                "bought_count": 0, # Счетчик купленного (начинаем с 0)
                "template_path": template_file_path # Абсолютный путь к сохраненному шаблону
            }
            # Добавляем новую запись в список
            self.item_data_list.append(new_item_entry)
            # Сортируем список по имени товара для удобства отображения
            self.item_data_list.sort(key=lambda x: x.get("name", "").lower())

            logger.info(f"Товар '{name}' успешно добавлен в список данных.")
            self.signal_update_status.emit(f"Добавлено: {name[:30]}...") # Обновляем статус в UI

            # --- 6. Обновление UI и сохранение данных ---
            self.signal_update_item_list.emit(self.get_item_data_for_display()) # Обновляем список в GUI
            self._save_item_data() # Сохраняем обновленный список данных в файл

            # --- 7. Завершение режима выделения ---
            self._finalize_selection_mode(success=True) # Завершаем режим выделения (успех)

        # --- Обработка ошибок при обработке выделенной области ---
        except (mss.ScreenShotError, ValueError, RuntimeError, IOError, cv2.error) as e:
            # Логируем конкретные ожидаемые ошибки
            logger.error(f"ОШИБКА обработки выделенной области: {type(e).__name__}: {e}")
            # При ошибке, если файл шаблона был частично создан, пытаемся его удалить
            if template_file_path and os.path.exists(template_file_path):
                 try:
                     os.remove(template_file_path)
                     logger.warning(f"Удален неполный/ошибочный файл шаблона: {template_file_path}")
                 except OSError:
                     pass # Игнорируем ошибку удаления
            # Обновляем статус в UI
            self.signal_update_status.emit(f"Ошибка добавления: {type(e).__name__} ({str(e)[:50]}...)")
            # Показываем сообщение пользователю
            QMessageBox.warning(
                None,
                "Ошибка добавления товара",
                f"Не удалось добавить товар:\n{type(e).__name__}: {e}\n\n"
                "Убедитесь, что область выделена корректно и содержит только название."
            )
            # Завершаем режим выделения (неуспех)
            self._finalize_selection_mode(False)

        except Exception:
            # Ловим любые другие неожиданные ошибки
            logger.exception("КРИТИЧЕСКАЯ НЕОЖИДАННАЯ ошибка при обработке выделенной области:")
            # При ошибке, если файл шаблона был частично создан, пытаемся его удалить
            if template_file_path and os.path.exists(template_file_path):
                 try:
                     os.remove(template_file_path)
                     logger.warning(f"Удален неполный/ошибочный файл шаблона: {template_file_path}")
                 except OSError:
                     pass # Игнорируем ошибку удаления
            # Обновляем статус в UI
            self.signal_update_status.emit("Критическая ошибка при добавлении.")
            # Показываем сообщение пользователю (глобальный обработчик тоже сработает, но можно показать здесь)
            QMessageBox.critical(
                None,
                "Критическая ошибка",
                f"Произошла критическая ошибка при добавлении товара.\nСм. лог файл."
            )
            # Завершаем режим выделения (неуспех)
            self._finalize_selection_mode(False)


    @pyqtSlot()
    def _handle_selection_cancelled(self):
        """Слот, вызываемый ScreenSelectionWidget при отмене выделения."""
        logger.info("<<< Режим выделения отменен пользователем.")
        # Проверяем, что мы действительно в режиме выделения
        if not self.is_selecting_area:
            logger.warning("Получен сигнал selection_cancelled, но режим выделения неактивен.")
            if self.m_screen_selector:
                self.m_screen_selector.hide() # Скрыть виджет на всякий случай
            return # Игнорируем сигнал

        # Скрываем виджет выделения
        if self.m_screen_selector:
             self.m_screen_selector.hide()
             # time.sleep(0.1) # Опциональная пауза

        # Обновляем статус в UI
        self.signal_update_status.emit("Выделение отменено.")

        # Завершаем режим выделения (неуспех)
        self._finalize_selection_mode(success=False)


    def _finalize_selection_mode(self, success: bool):
        """
        Завершает режим выделения области: сбрасывает флаг, скрывает виджет
        (если еще виден), разблокирует UI контролы.
        """
        status_log = "Успешно завершен" if success else "Отменен/Завершен с ошибкой"
        logger.info(f"--- Завершение режима выделения ({status_log}) ---")

        # Проверяем, что режим выделения был активен
        if not self.is_selecting_area:
            logger.warning("Попытка финализировать режим выделения, когда он неактивен.")
            return # Ничего не делаем, если флаг уже сброшен

        # Сбрасываем флаг режима выделения
        self.is_selecting_area = False

        # Скрываем виджет выделения, если он еще виден
        if self.m_screen_selector and self.m_screen_selector.isVisible():
            logger.debug("Скрытие ScreenSelectionWidget.")
            self.m_screen_selector.hide()
            # Опционально: отключаем сигналы, чтобы избежать срабатывания после удаления
            # self.m_screen_selector.area_selected.disconnect(self._handle_area_selected)
            # self.m_screen_selector.selection_cancelled.disconnect(self._handle_selection_cancelled)
            # self.m_screen_selector.deleteLater() # Можно удалить виджет, если он не переиспользуется
            # self.m_screen_selector = None # Обнулить ссылку, если удалили

        # Разблокируем контролы UI, если мониторинг не активен
        if not self.monitoring_active:
            self.signal_enable_controls.emit(True)
            logger.info("Контролы UI разблокированы.")
            # Сбрасываем статус UI на "Готов." через небольшую задержку,
            # если текущий статус не является результатом действия или ошибки.
            # Вместо прямого доступа, просто запускаем таймер в MainThread,
            # который проверит статус и сбросит его.
            # Сигнал enable_controls в MainWindow уже содержит эту логику.


    # --- Методы управления мониторингом ---
    @pyqtSlot()
    def start_monitoring(self):
        """
        Запускает процесс автоматического поиска и покупки товаров в отдельном потоке (Worker).
        Вызывается при клике на кнопку "Начать АВТО-поиск".
        """
        logger.info("--- Запрос на запуск мониторинга ---")
        # Проверяем текущее состояние приложения
        if self.monitoring_active:
            self.signal_update_status.emit("Уже запущен!");
            logger.warning("Попытка запустить мониторинг, когда он уже активен.")
            return
        if self.is_selecting_area:
            self.signal_update_status.emit("Завершите выделение!");
            logger.warning("Попытка запустить мониторинг во время режима выделения.")
            return

        # Проверяем, инициализированы ли необходимые ресурсы (MSS, OCR)
        # BotLogic._init_resources уже выполнился при создании BotLogic
        if not self.initialized_ok:
            self.signal_update_status.emit("Ошибка инициализации системы!");
            logger.error("Система не инициализирована корректно, невозможно запустить мониторинг.")
            QMessageBox.critical(None, "Ошибка Запуска", "Система не инициализирована корректно. Перезапустите приложение.")
            return
        if self.m_ocr_reader is None or self.m_sct is None:
            self.signal_update_status.emit("Ошибка ресурсов (MSS/OCR)!");
            logger.error("MSS или OCR недоступны, невозможно запустить мониторинг.")
            QMessageBox.critical(None, "Ошибка Запуска", "MSS или OCR недоступны. Перезапустите приложение.")
            return


        # Фильтруем и валидируем список товаров, которые будут переданы Worker'у
        # В Worker передаются только включенные товары с существующим файлом шаблона.
        items_for_worker = self._filter_and_validate_items()

        # Проверка, есть ли вообще что искать после фильтрации
        if not items_for_worker:
            self.signal_update_status.emit("Нет товаров для поиска.");
            logger.warning("Нет активных товаров с валидными шаблонами для передачи Worker'у.")
            QMessageBox.warning(None, "Нет товаров для поиска", "Не выбрано ни одного активного товара с существующим файлом шаблона.")
            return

        # Проверка, не работает ли предыдущий Worker/Thread
        # Это должно быть уже обработано при вызове stop_monitoring(),
        # но добавим проверку на всякий случай.
        if self.m_thread and self.m_thread.isRunning():
            logger.warning("Предыдущий Worker/Thread еще активен. Попытка принудительной остановки.")
            # Если поток еще жив, пытаемся его остановить перед запуском нового
            self.stop_monitoring()
            # Ожидаем завершения предыдущего потока (с таймаутом)
            wait_time_ms = 2000 # Ждем до 2 секунд
            if self.m_thread and not self.m_thread.wait(wait_time_ms):
                logger.critical(f"!!! Предыдущий Worker/Thread не завершился за {wait_time_ms} мс. Невозможно запустить новый.")
                self.signal_update_status.emit("Ошибка: Предыдущий процесс не остановился!")
                # Нельзя безопасно запустить новый Worker, выходим.
                # Можно показать сообщение об ошибке.
                QMessageBox.critical(None, "Ошибка Запуска", "Не удалось остановить предыдущий процесс. Попробуйте перезапустить приложение.")
                return
            else:
                logger.info("Предыдущий Worker/Thread успешно остановлен.")
                # Очищаем ссылки после успешной остановки
                self.m_worker = None
                self.m_thread = None
                # Даем немного времени системе
                time.sleep(0.1)
                if QApplication.instance():
                    QApplication.instance().processEvents()


        # Очищаем ссылки на старый Worker и Thread перед созданием новых
        self.m_worker = None
        self.m_thread = None

        try:
            logger.info("Создание нового Worker и QThread для мониторинга...")
            # Создаем новый поток Qt
            self.m_thread = QThread(self)
            # Устанавливаем имя потока Qt для отладки
            self.m_thread.setObjectName("MonitoringWorkerThread")

            # Создаем новый Worker, передаем ему список товаров и OCR Reader
            self.m_worker = Worker(items_for_worker, self.m_ocr_reader)
            logger.info(f"Worker ID '{id(self.m_worker)}' создан.")

            # Перемещаем Worker объект в созданный поток
            self.m_worker.moveToThread(self.m_thread)
            logger.info(f"Worker перемещен в поток '{self.m_thread.objectName()}'.")

            # Подключаем сигналы от Worker'а к соответствующим слотам BotLogic
            self._connect_worker_signals()
            logger.info("Сигналы Worker <-> BotLogic соединены.")

            # Устанавливаем флаг активности мониторинга
            self.monitoring_active = True
            # Отправляем сигнал UI для блокировки контролов и обновления статуса
            self.signal_enable_controls.emit(False) # UI заблокирует управление данными и кнопку "Старт"

            # Обновляем статус в UI
            n = len(items_for_worker)
            msg = f"Запуск поиска для {n} товаров..."
            self.signal_update_status.emit(msg)
            logger.info(f">>> {msg}")

            # Запускаем поток. При запуске потока (сигнал started), будет вызван метод run() Worker'а.
            self.m_thread.start()
            logger.info(f"Поток '{self.m_thread.objectName()}' запущен.")

        except Exception as e:
            # Ловим любые ошибки при создании или запуске Worker/Thread
            logger.exception("КРИТИЧЕСКАЯ ошибка при создании или запуске Worker/Thread:")
            self.monitoring_active = False # Убеждаемся, что флаг сброшен
            self.signal_enable_controls.emit(True) # Разблокируем UI контролы
            self.signal_update_status.emit("Критическая ошибка запуска потока!")
            # Попытка очистить созданные объекты Worker/Thread
            if self.m_worker:
                self.m_worker.deleteLater()
                self.m_worker = None
            if self.m_thread:
                self.m_thread.quit()
                self.m_thread.wait(500)
                self.m_thread.deleteLater()
                self.m_thread = None
            # Сообщаем пользователю об ошибке
            QMessageBox.critical(None, "Ошибка Запуска", f"Не удалось запустить процесс поиска:\n{e}\nПопробуйте перезапустить приложение.")


    def _filter_and_validate_items(self) -> list:
        """
        Фильтрует список товаров, оставляя только те, которые включены
        и имеют существующий файл шаблона.
        Проверяет и исправляет абсолютность путей к шаблонам, если необходимо.
        Возвращает новый список словарей для Worker'а.
        """
        logger.info("Фильтрация и валидация товаров для Worker'а...")
        valid_items = []
        needs_resave = False # Флаг, нужно ли пересохранить файл данных

        for item in self.item_data_list:
            # Проверяем, включен ли товар (по умолчанию False)
            if not item.get("enabled", False):
                # logger.debug(f"Товар '{item.get('name','N/A')}' выключен. Пропущен.")
                continue # Пропускаем выключенные товары

            name = item.get("name")
            path = item.get("template_path")

            # Проверяем наличие имени и пути к шаблону
            if not name or not isinstance(name, str) or not path or not isinstance(path, str):
                logger.warning(f"Товар с некорректными данными (имя/путь): {item}. Пропущен.")
                continue

            # Проверяем абсолютность пути и исправляем, если нужно
            if not os.path.isabs(path):
                abs_path = os.path.abspath(os.path.join(BASE_DIR, path))
                # Ищем этот элемент в оригинальном списке self.item_data_list
                # и обновляем его путь там.
                original_item = self.get_item_data_by_name(name)
                if original_item:
                     original_item["template_path"] = abs_path
                     needs_resave = True
                path = abs_path # Используем абсолютный путь для дальнейшей проверки

            # Проверяем существование файла шаблона по (возможно, исправленному) пути
            if os.path.exists(path):
                # Если товар включен И имеет существующий шаблон, добавляем его в список для Worker'а
                # Копируем данные, чтобы Worker работал с независимой копией
                item_copy = item.copy()
                # Убеждаемся, что bought_count сброшен для нового запуска
                item_copy['bought_count'] = 0 # Должен быть сброшен при загрузке, но на всякий случай
                valid_items.append(item_copy)
            else:
                logger.warning(f"Шаблон НЕ НАЙДЕН для включенного товара '{name}' по пути '{path}'. Товар пропущен при запуске поиска.")
                # Можно опционально уведомить пользователя, но UI уже должен показывать отсутствие шаблона цветом.

        # Если были исправлены относительные пути, сохраняем данные
        if needs_resave:
             logger.info("Некоторые пути к шаблонам были исправлены. Вызов _save_item_data().")
             self._save_item_data()

        logger.info(f"Фильтрация завершена. Найдено {len(valid_items)} валидных товаров для передачи Worker'у.")
        return valid_items # Возвращаем список товаров для Worker'а

    def _connect_worker_signals(self):
        """Подключает сигналы от Worker'а к соответствующим слотам BotLogic."""
        if not self.m_worker or not self.m_thread:
            logger.critical("Ошибка соединения сигналов Worker'а: m_worker или m_thread равен None.")
            return

        # Используем QueuedConnection для безопасной межпоточной связи
        conn_type = Qt.ConnectionType.QueuedConnection

        # Сигнал ошибки Worker'а -> слот обработки ошибки в BotLogic
        self.m_worker.error.connect(self._handle_worker_error, conn_type)

        # Сигнал выполнения действия Worker'ом -> слот обработки действия в BotLogic
        self.m_worker.action_performed_signal.connect(self._handle_action_performed, conn_type)

        # Сигнал завершения работы Worker'а -> слот обработки завершения в BotLogic
        self.m_worker.finished.connect(self._handle_worker_finished, conn_type)

        # Сигнал запуска потока Qt -> вызов метода run() Worker'а
        # Этот сигнал исходит от QThread после успешного start()
        self.m_thread.started.connect(self.m_worker.run, conn_type)

        # Сигнал завершения работы Worker'а -> выход из цикла событий потока Qt
        # Когда Worker закончит run(), он отправит finished, который вызовет quit() потока
        self.m_worker.finished.connect(self.m_thread.quit, conn_type)

        # Сигнал завершения работы Worker'а -> удаление объекта Worker после завершения его работы в его потоке
        self.m_worker.finished.connect(self.m_worker.deleteLater, conn_type)

        # Сигнал завершения работы потока Qt -> сброс ссылок в BotLogic
        # Это должно быть последнее, что происходит
        self.m_thread.finished.connect(self._clear_worker_thread_refs, conn_type)

        logger.info("Соединения сигналов Worker -> BotLogic установлены.")


    @pyqtSlot()
    def stop_monitoring(self):
        """
        Запрашивает остановку Worker'а и процесса мониторинга.
        Вызывается из основного потока (GUI или хоткей).
        """
        logger.info("--- Запрос на остановку мониторинга ---")
        # Проверяем, активен ли мониторинг
        if not self.monitoring_active:
            logger.info("Мониторинг уже не активен.")
            # Возможно, UI не синхронизирован, сбросим флаг и обновим контролы
            self.monitoring_active = False
            if not self.is_selecting_area: # Не разблокируем, если в режиме выделения
                self.signal_enable_controls.emit(True)
            self.signal_update_status.emit("Мониторинг уже остановлен.")
            # Убедимся, что ссылки на Worker/Thread сброшены, если их нет или они неактивны
            if (self.m_thread is None or not self.m_thread.isRunning()) and self.m_worker is None:
                 self.m_worker = None
                 self.m_thread = None # Сброс ссылок если поток уже завершился сам
            return

        # Если мониторинг активен и есть Worker/Thread
        if self.m_thread and self.m_worker:
            worker_id = getattr(self.m_worker, "worker_id", "N/A")
            logger.info(f"Отправка команды остановки Worker'у (ID: {worker_id})...")

            # Обновляем UI немедленно для обратной связи с пользователем
            self.monitoring_active = False # Сбрасываем флаг в основном потоке
            if not self.is_selecting_area:
                 self.signal_enable_controls.emit(True) # Разблокируем контролы (кроме Старт)
            self.signal_update_status.emit("Остановка поиска...")

            # Безопасно вызываем метод stop() Worker'а в его потоке через QueuedConnection
            # Этот вызов не блокирует основной поток.
            QMetaObject.invokeMethod(
                self.m_worker,
                "stop",
                Qt.ConnectionType.QueuedConnection
            )
            logger.info("Команда worker.stop() отправлена в очередь Worker'а.")

            # Ожидание завершения потока Worker'а происходит в cleanup()
            # или при автоматическом завершении после получения сигнала finished.
            # Здесь в UI потоке мы просто отправили команду и обновили UI.

        else:
            # Не должно происходить, если monitoring_active == True
            logger.error("Запрос стоп, но флаг monitoring_active установлен, а Worker/Thread равен None или неактивен. Сброс состояния.")
            self.monitoring_active = False
            if not self.is_selecting_area:
                self.signal_enable_controls.emit(True)
            self.signal_update_status.emit("Состояние сброшено.")
            self.m_worker = None
            self.m_thread = None # Убедимся, что ссылки None

    # --- Слоты для обработки сигналов от Worker'а (выполняются в основном потоке) ---
    @pyqtSlot(str)
    def _handle_worker_error(self, error_msg: str):
        """Обрабатывает сигнал ошибки от Worker'а."""
        logger.error(f"Получен сигнал ошибки от Worker'а: {error_msg}")
        # Обновляем статус в UI
        self.signal_update_status.emit(f"Ошибка Worker: {error_msg}")
        # Можно показать QMessageBox для пользователя
        # QMessageBox.warning(None, "Ошибка Worker", f"Произошла ошибка в фоновом процессе: {error_msg}")
        # Остановка Worker'а при ошибке уже реализована внутри Worker'а,
        # он сам отправит finished сигнал после ошибки.

    @pyqtSlot(str, int, int)
    def _handle_action_performed(self, name: str, price: int, total_bought_count: int):
        """
        Обрабатывает сигнал о выполненном действии Worker'ом.
        Обновляет UI и данные о товаре.
        Выполняется в основном (UI) потоке.
        """
        logger.info(f"[MainThread] Получен сигнал ДЕЙСТВИЯ: '{name}' ({total_bought_count}) за {price}$.")

        # Находим товар в основном списке данных BotLogic
        item = self.get_item_data_by_name(name)
        if item:
            # Обновляем счетчик купленного в основном списке данных
            item["bought_count"] = total_bought_count
            # NOTE: Сохранение данных после КАЖДОГО действия может быть неэффективным.
            # Возможно, лучше сохранять реже (напр., раз в минуту или при остановке).
            # Пока оставляем сохранение при каждом действии для гарантии,
            # что прогресс не потеряется при внезапном закрытии.
            self._save_item_data()
            target_qty = item.get("quantity", "?")
            status = f"Действие: {name[:20]}... ({total_bought_count}/{target_qty}) за {price}$"
            self.signal_update_status.emit(status) # Обновляем статус в UI
            # UI (MainWindow) также слушает этот сигнал и обновит список и проиграет звук.
            self.signal_action_performed.emit(name, price, total_bought_count)

            # Проверка, достигнута ли цель для этого конкретного товара
            if total_bought_count >= item.get("quantity", 1):
                 logger.info(f"Цель ({target_qty}) для товара '{name}' достигнута.")
                 # Worker сам проверяет, достигнуты ли ВСЕ цели и останавливается.
        else:
            logger.warning(f"[MainThread] Получен сигнал действия для неизвестного товара '{name}'.")


    @pyqtSlot(bool)
    def _handle_worker_finished(self, stopped_by_target: bool):
        """
        Обрабатывает сигнал finished от Worker'а.
        Означает, что Worker завершил свою работу (штатно или с ошибкой/остановкой).
        Выполняется в основном (UI) потоке.
        """
        # Получаем ссылку на Worker, отправивший сигнал
        worker_obj = self.sender()
        worker_id = getattr(worker_obj, "worker_id", "N/A")
        reason = "по достижению всех целей" if stopped_by_target else "по команде Стоп или из-за ошибки"
        logger.info(f"--- Получен сигнал Worker.finished от Worker ID '{worker_id}' ({reason}) ---")

        # Сброс флага активности мониторинга в основном потоке
        # (Это уже делается в stop_monitoring перед отправкой команды Worker'у,
        # но повторим на всякий случай, если Worker завершился сам по себе).
        self.monitoring_active = False

        # Обновляем статус в UI
        status = "Все цели достигнуты!" if stopped_by_target else "Поиск остановлен."
        self.signal_update_status.emit(status)

        # Разблокируем контролы UI, если режим выделения не активен
        if not self.is_selecting_area:
            self.signal_enable_controls.emit(True) # UI обновится и разблокируется

        # Отправляем сигнал в MainWindow для финализации состояния UI
        self.signal_monitoring_stopped.emit(stopped_by_target)
        logger.info(f"[MainThread] Сигнал signal_monitoring_stopped({stopped_by_target}) отправлен в UI.")

        # Worker и Thread будут автоматически удалены через deleteLater()
        # после того, как этот слот завершится. Ссылки будут обнулены в _clear_worker_thread_refs.


    @pyqtSlot()
    def _clear_worker_thread_refs(self):
        """
        Слот, вызываемый после завершения работы QThread.
        Сбрасывает ссылки на Worker и Thread в BotLogic.
        Выполняется в основном (UI) потоке после завершения потока Worker'а.
        """
        thread_obj = self.sender() # Получаем ссылку на QThread, который отправил сигнал
        thread_name = thread_obj.objectName() if thread_obj else "N/A"
        worker_id = getattr(self.m_worker, "worker_id", "N/A_before_clear") # ID Worker'а перед обнулением

        log_msg = (
            f"[MainThread] --- Сигнал QThread.finished от '{thread_name}'. "
            f"Очистка ссылок (Worker ID был '{worker_id}'). ---"
        )
        logger.info(log_msg)

        # Сбрасываем ссылки
        self.m_worker = None
        self.m_thread = None
        logger.info("[MainThread] Ссылки m_worker и m_thread обнулены.")

        # Финальная проверка состояния контролов UI.
        # Это важно, если остановка произошла не через stop_monitoring() (напр., ошибка в Worker)
        # signal_enable_controls(True) мог быть вызван раньше, но эта проверка гарантирует,
        # что UI разблокирован, если никакие активные режимы не запущены.
        if not self.monitoring_active and not self.is_selecting_area:
            self.signal_enable_controls.emit(True)
            logger.info("[MainThread] Контролы проверены/разблокированы после завершения потока.")


    # --- Метод очистки при закрытии ---
    def cleanup(self):
        """
        Выполняет упорядоченную очистку ресурсов перед завершением приложения.
        Вызывается из MainWindow.closeEvent.
        """
        # Устанавливаем флаг, чтобы знать, что очистка была вызвана
        self.cleanup_called = True
        logger.info("--- Запуск очистки BotLogic ---")

        # 1. Сохраняем данные о товарах (на случай, если были изменения)
        logger.info("Сохранение данных о товарах...")
        self._save_item_data()
        logger.info("Данные о товарах сохранены.")

        # 2. Отключаем глобальные горячие клавиши
        logger.info("Отключение глобальных горячих клавиш...")
        try:
            # Если модуль keyboard был импортирован и имеет функцию unhook_all
            if "keyboard" in sys.modules and hasattr(keyboard, "unhook_all"):
                keyboard.unhook_all()
                logger.info("Глобальные хоткеи отключены.")
        except Exception:
             logger.exception("Ошибка при отключении глобальных хоткеев:")


        # 3. Закрытие и удаление виджета выделения области (если существует и виден)
        if self.m_screen_selector:
            logger.info("Закрытие и удаление ScreenSelectionWidget...")
            try:
                # Скрываем виджет
                if self.m_screen_selector.isVisible():
                     self.m_screen_selector.hide()
                     # Небольшая пауза, чтобы окно скрылось
                     time.sleep(0.05)
                     if QApplication.instance():
                         QApplication.instance().processEvents()

                # Отключаем сигналы, чтобы избежать срабатывания после удаления
                try:
                     self.m_screen_selector.area_selected.disconnect(self._handle_area_selected)
                     self.m_screen_selector.selection_cancelled.disconnect(self._handle_selection_cancelled)
                     logger.debug("Сигналы ScreenSelectionWidget отключены.")
                except Exception as disc_e:
                    logger.warning(f"Не удалось полностью отключить сигналы ScreenSelectionWidget: {disc_e}")

                # Запрашиваем удаление объекта виджета
                self.m_screen_selector.deleteLater()
                self.m_screen_selector = None # Обнуляем ссылку
                logger.info("ScreenSelectionWidget закрыт и помечен для удаления.")
            except Exception as e:
                logger.error(f"Ошибка при закрытии или удалении ScreenSelectionWidget: {e}")
                self.m_screen_selector = None # Обнулить ссылку даже при ошибке


        # 4. Oстановка Worker-потока, если он активен
        # Проверяем, активен ли мониторинг И существует ли поток
        if self.monitoring_active or (self.m_thread and self.m_thread.isRunning()):
            logger.info("Мониторинг активен при закрытии. Запрашиваем остановку Worker'а...")
            # Вызываем stop_monitoring(). Это отправит команду Worker'у и обновит UI флаги.
            self.stop_monitoring()

            # Ожидаем завершения потока Worker'а.
            # Это важно, чтобы Worker успел завершить текущие операции и очистить свои ресурсы (напр. MSS).
            # Устанавливаем таймаут на ожидание, чтобы приложение не зависло навсегда.
            if self.m_thread:
                wait_time_ms = 3000 # Ждем до 3 секунд
                logger.info(f"Ожидание завершения потока Worker'а '{self.m_thread.objectName() or 'N/A'}' ({wait_time_ms} мс)...")
                if not self.m_thread.wait(wait_time_ms):
                    logger.critical("!!! Поток Worker не завершился штатно в отведенное время!")
                    # Если поток не завершился, возможно, он завис.
                    # В этом случае мы не можем безопасно освободить его ресурсы.
                else:
                    logger.info("Поток Worker завершен.")

            # После ожидания (или если поток не существовал/не был запущен),
            # ссылки на Worker и Thread должны быть None
            # (благодаря _clear_worker_thread_refs, вызванному через сигнал finished потока)
            self.m_worker = None
            self.m_thread = None
            self.monitoring_active = False # Убедимся, что флаг сброшен

        else:
             logger.info("Мониторинг не был активен при закрытии.")


        # 5. Закрытие основного экземпляра MSS
        if self.m_sct:
            logger.info("Закрытие основного экземпляра MSS...")
            try:
                self.m_sct.close()
                logger.info("Основной MSS закрыт.")
            except Exception as e:
                logger.error(f"Ошибка при закрытии основного MSS: {e}")
            self.m_sct = None # Обнуляем ссылку


        # 6. Освобождение EasyOCR Reader
        if self.m_ocr_reader:
            logger.info("Освобождение EasyOCR Reader...")
            try:
                # EasyOCR не имеет явного метода close/shutdown.
                # Просто удаляем ссылку, сборщик мусора Python позаботится об остальном.
                # Если OCRReader создан в Worker'е, то его очистка происходит в Worker'е.
                # Здесь очищается инстанс, переданный Worker'у (созданный в BotLogic).
                del self.m_ocr_reader
                logger.info("EasyOCR Reader освобожден.")
            except Exception as e:
                logger.error(f"Ошибка при освобождении EasyOCR Reader: {e}")
            self.m_ocr_reader = None # Обнуляем ссылку

        logger.info("--- Очистка BotLogic завершена ---")
        # В конце очистки логики, можно явно завершить логирование,
        # чтобы все буферы были сброшены на диск.
        logging.shutdown()