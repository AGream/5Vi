import sys
import os

# Определение BASE_DIR, как в main.py
try:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        BASE_DIR = os.path.dirname(sys.executable)
    elif '__file__' in globals():
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    else:
        BASE_DIR = os.getcwd()
except Exception:
    BASE_DIR = os.getcwd()

# Добавление BASE_DIR в sys.path необходимо для импорта локальных модулей
# в one-file сборке PyInstaller или при запуске из другой директории.
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Теперь можно безопасно импортировать main
try:
    import main
except ImportError as e:
    # Это маловероятно, если предыдущие импорты в main.py прошли успешно,
    # но на всякий случай.
    print(f"Критическая ошибка: Не удалось импортировать main.py: {e}", file=sys.stderr)
    # Здесь нет QApplication, просто выходим
    sys.exit(1)

# Запуск основного скрипта
if __name__ == "__main__":
    # main.py содержит блок if __name__ == '__main__':
    # который инициализирует QApplication и запускает основной цикл.
    # Просто делегируем выполнение туда.
    main # Выполнение кода модуля main происходит при импорте.
    # Чтобы запустить блок if __name__ == '__main__': в main.py,
    # нужно убедиться, что main.__name__ == '__main__'.
    # В обычном импорте __name__ модуля становится именем модуля ('main').
    # Для запуска как основного скрипта, можно сделать так:

    # Сохраняем оригинальное значение __name__ текущего модуля
    original_name = __name__

    # Временно меняем __name__ модуля main на '__main__', чтобы его блок выполнился
    if hasattr(main, '__name__'):
        main.__name__ = '__main__'

    # Запускаем main.py. Код внутри его if __name__ == '__main__': выполнится.
    # Не вызываем main.main() или что-то подобное, просто позволяем скрипту исполниться.

    # После того как main.py завершится (например, sys.exit), этот скрипт тоже завершится.
    # Если main.py не завершается явно, а просто выходит из своего __main__ блока,
    # то выполнение продолжится здесь. Но в нашем случае main.py вызывает sys.exit().

    # Можно добавить print для отладки последовательности выполнения
    # print("run.py завершает работу (после выполнения main.py).", file=sys.stderr