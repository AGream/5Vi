# --- START OF FILE main.py ---

# main.py
"""Точка входа в приложение. Инициализация и запуск GUI."""

import sys
import os
import traceback
import datetime
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt # Импорт для QTimer

# --- Определение базовой директории приложения ---
# Необходимо определить до импорта других модулей, которые могут его использовать.
try:
    # PyInstaller создает временную папку и сохраняет путь в sys._MEIPASS,
    # но нам нужна директория рядом с .exe
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Путь к исполняемому файлу .exe
        BASE_DIR = os.path.dirname(sys.executable)
    elif '__file__' in globals():
        # Обычный запуск .py скрипта
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    else:
        # Фоллбэк на текущую рабочую директорию
        BASE_DIR = os.getcwd()
except Exception:
    # Если не удалось определить __file__ или sys._MEIPASS
    BASE_DIR = os.getcwd()
# --- Конец определения BASE_DIR ---

# Добавляем BASE_DIR в sys.path, чтобы локальные модули были найдены,
# особенно важно для PyInstaller в one-file mode.
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# --- Импорт локальных модулей ---
# Порядок: стандартные -> сторонние -> локальные
try:
    # Импорты локальных модулей после определения BASE_DIR
    from interface import MainWindow
    # Импорт BotLogic для его использования, BASE_DIR из constants
    from logic import BotLogic, BASE_DIR as LOGIC_BASE_DIR
    from constants import ADD_ITEM_HOTKEY, STOP_MONITORING_HOTKEY
except ImportError as e:
    print(f"КРИТИЧЕСКАЯ ОШИБКА: Не найдены файлы приложения: {e}",
          file=sys.stderr)
    # Попытка показать сообщение, если PyQt6 доступен
    try:
        app = QApplication([]) # Создаем минимальное приложение для сообщения
        QMessageBox.critical(
            None, "Ошибка Загрузки",
            f"Не найдены необходимые файлы приложения:\n{e}\n"
            "Убедитесь, что все файлы (interface.py, logic.py, "
            "constants.py, screen_selector.py и папки) находятся в той же "
            "директории.\nПриложение будет закрыто."
        )
        # Не запускаем app.exec()
    except Exception:
        pass # Не удалось показать сообщение или создать QApplication
    sys.exit(1) # Всегда выходим при ошибке импорта

# Проверка согласованности BASE_DIR (на всякий случай, должно совпадать
# после sys.path.insert)
if BASE_DIR != LOGIC_BASE_DIR:
    print(f"ПРЕДУПРЕЖДЕНИЕ: Несоответствие BASE_DIR! "
          f"main.py: {BASE_DIR}, logic.py: {LOGIC_BASE_DIR}",
          file=sys.stderr)
    # Используем BASE_DIR, определенный в main.py как канонический
    # для логов и сообщений здесь.

def global_except_hook(exctype, value, tb):
    """
    Глобальный обработчик необработанных исключений.
    Логирует ошибку в файл и показывает сообщение пользователю.
    """
    # Используем BASE_DIR из main.py для лог-файла
    log_filename = "error_log.txt"
    log_path = os.path.join(BASE_DIR, log_filename)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Формируем сообщение об ошибке
    error_message = f"--- Необработанное исключение ({timestamp}) ---\n"
    error_message += f"Тип: {exctype.__name__}\n"
    error_message += f"Значение: {value}\n"
    error_message += "Traceback:\n"
    error_message += "".join(traceback.format_exception(exctype, value, tb))
    error_message += "-------------------------------------------\n"

    print("\n--- ГЛОБАЛЬНОЕ ИСКЛЮЧЕНИЕ ---", file=sys.stderr, flush=True)
    print(error_message, file=sys.stderr, flush=True)
    print("--- КОНЕЦ ИСКЛЮЧЕНИЯ ---", file=sys.stderr, flush=True)

    # Попытка записи в лог-файл
    log_msg_display = "Не удалось записать лог ошибки."
    try:
        with open(log_path, "a", encoding='utf-8') as f:
            f.write(error_message)
        print(f"Подробности ошибки записаны в файл: {log_path}",
              file=sys.stderr, flush=True)
        log_msg_display = f"Подробности в файле: {log_filename}"
    except Exception as log_e:
        print(f"Критическая ошибка: Не удалось записать лог в файл {log_path}: "
              f"{log_e}", file=sys.stderr, flush=True)


    # Показываем сообщение пользователю. Убедимся, что QApplication существует.
    app = QApplication.instance() # Получаем существующий экземпляр
    if app is None:
         print("Критическая ошибка: QApplication не существует для показа сообщения об ошибке.", file=sys.stderr)
    else:
        try:
            QMessageBox.critical(
                None, "Критическая ошибка",
                f"Произошла непредвиденная ошибка:\n{exctype.__name__}: {value}\n\n"
                f"{log_msg_display}\nПриложение будет закрыто."
            )
        except Exception as msg_e:
             print(f"Критическая ошибка: Не удалось показать QMessageBox: {msg_e}", file=sys.stderr)

    # Завершаем приложение
    sys.exit(1)


# Устанавливаем глобальный обработчик исключений
sys.excepthook = global_except_hook

# --- Основная точка входа ---
if __name__ == '__main__':
    # Создаем экземпляр QApplication, если он еще не создан (например,
    # глобальным обработчиком при ошибке импорта)
    app = QApplication.instance()
    if app is None:
        print("Создание QApplication...", flush=True)
        app = QApplication(sys.argv)
        print("QApplication создан.", flush=True)
        # Устанавливаем, чтобы приложение завершалось при закрытии последнего окна
        app.setQuitOnLastWindowClosed(True)
    else:
        print("QApplication уже существует.", flush=True)


    print("Инициализация приложения...", flush=True)
    print(f"Используется базовая директория: {BASE_DIR}", flush=True)

    # Создаем экземпляр логики приложения
    # Логика должна быть создана до MainWindow, т.к. передается в конструктор
    print("Создание BotLogic...", flush=True)
    try:
        # Создаем логику. Логика может вызвать global_except_hook
        # или показать QMessageBox сама при критической ошибке инициализации
        logic = BotLogic()
        # Если BotLogic не смог инициализироваться и сам не вызвал выход,
        # проверим его состояние
        if not hasattr(logic, 'initialized_ok') or not logic.initialized_ok:
             print("BotLogic не инициализирован успешно. Выход.", file=sys.stderr)
             sys.exit(1) # Явный выход, если логика сообщила о неудаче
        print("BotLogic создан и инициализирован успешно.", flush=True)
    except Exception as e:
        print("Создание MainWindow...", flush=True)
    try:
        window = MainWindow(logic)
        print("MainWindow создано.", flush=True)
    except Exception as e:
         print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось создать MainWindow: {e}", file=sys.stderr)
         global_except_hook(type(e), e, e.__traceback__) # Логируем и выходим

    # Отображаем главное окно
    print("Отображение MainWindow...", flush=True)
    window.show()
    print("Приложение готово к работе.", flush=True)
    print(f"Для добавления товара используйте хоткей: "
          f"'{ADD_ITEM_HOTKEY.upper()}'", flush=True)
    print(f"Для остановки поиска используйте хоткей: "
          f"'{STOP_MONITORING_HOTKEY}' (Numpad)", flush=True)
    print("!!! Для работы глобальных горячих клавиш могут требоваться "
          "права администратора !!!", flush=True)

    # Запускаем главный цикл обработки событий Qt
    # app.exec() блокирует выполнение до завершения работы приложения
    print("Запуск цикла событий QApplication...", flush=True)
    exit_code = app.exec()

    # Код после завершения цикла событий (при закрытии окна)
    print(f"Приложение завершает работу с кодом: {exit_code}", flush=True)

    # cleanup() вызывается в MainWindow.closeEvent, который обрабатывается
    # перед завершением app.exec(). Дополнительный вызов здесь не нужен,
    # но можно убедиться, что он вызван.
    # if hasattr(logic, 'cleanup_called') and not logic.cleanup_called:
    #    print("WARN: Logic cleanup was not called via closeEvent.", file=sys.stderr)
    #    logic.cleanup() # Повторный вызов, если по какой-то причине не сработало

    # Выход из скрипта с кодом завершения приложения
    sys.exit(exit_code)

# --- END OF FILE main.py ---