# --- START OF FILE screen_selector.py ---

# screen_selector.py
"""Модуль виджета для выделения области на экране."""

from PyQt6.QtWidgets import QWidget, QApplication
# Исправлен импорт QGuiApplication
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QCursor, QScreen, QGuiApplication
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, pyqtSlot
import sys  # Для вывода в stderr
import time # Для отладочных пауз

class ScreenSelectionWidget(QWidget):
    """
    Прозрачный полноэкранный виджет для выделения прямоугольной области
    экрана с помощью мыши.
    """
    area_selected = pyqtSignal(QRect) # Сигнал при успешном выделении
    selection_cancelled = pyqtSignal() # Сигнал при отмене (ESC или ПКМ)

    def __init__(self, parent=None):
        """Инициализатор виджета."""
        super().__init__(parent)
        self._start_pos = QPoint()
        self._end_pos = QPoint()
        self._is_selecting = False # Флаг, активно ли выделение
        self._selection_rect = QRect() # Текущий прямоугольник выделения

        # Устанавливаем флаги окна:
        # FramelessWindowHint: Без рамки и заголовка
        # WindowStaysOnTopHint: Всегда поверх других окон
        # Tool: Не появляется на панели задач (опционально, но удобно)
        # CustomizeWindowHint: Позволяет комбинировать флаги
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.CustomizeWindowHint # Нужен для комбинации флагов
        )
        # Делаем фон прозрачным
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Устанавливаем курсор перекрестия для удобства выделения
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Настройки отрисовки выделенной области
        self._pen_color = QColor(255, 0, 0, 200) # Красный, полупрозрачный
        self._pen_width = 2
        self._brush_color = QColor(100, 100, 100, 70) # Серый, полупрозрачный (затеняет фон)

    def _get_virtual_desktop_geometry(self) -> QRect:
        """
        Возвращает геометрию всего виртуального рабочего стола,
        охватывающего все мониторы.
        """
        # Используем QGuiApplication для доступа к информации о мониторах
        app = QGuiApplication.instance()
        if app is None:
            # Если QGuiApplication не существует (что крайне маловероятно
            # в Qt приложении), фоллбэк
            print("[ScreenSelector] Warning: QGuiApplication instance is None.",
                  file=sys.stderr, flush=True)
            return QApplication.desktop().screenGeometry() # Устаревший метод, но может сработать

        screens = app.screens()
        if not screens:
             print("[ScreenSelector] Critical: No screens found via QGuiApplication!",
                   file=sys.stderr, flush=True)
             return QRect(0, 0, 800, 600) # Абсолютный фоллбэк, если нет экранов

        # Получаем геометрию всех экранов и объединяем их
        virtual_rect = QRect()
        for screen in screens:
            virtual_rect = virtual_rect.united(screen.geometry())

        print(f"[ScreenSelector] Virtual desktop geometry: {virtual_rect.x()},{virtual_rect.y()},{virtual_rect.width()},{virtual_rect.height()}",
              file=sys.stderr, flush=True)
        return virtual_rect


    def showEvent(self, event):
        """Обработчик события показа виджета."""
        print("[ScreenSelector] Show event", flush=True)
        try:
            # Устанавливаем геометрию виджета на весь виртуальный рабочий стол
            screen_geometry = self._get_virtual_desktop_geometry()
            self.setGeometry(screen_geometry)
            print(f"[ScreenSelector] Widget geometry set to: {self.geometry().x()},{self.geometry().y()},{self.geometry().width()},{self.geometry().height()}",
                  file=sys.stderr, flush=True)

        except Exception as e:
             print(f"[ScreenSelector] Error setting geometry: {e}",
                   file=sys.stderr, flush=True)
             # Устанавливаем размер по умолчанию в случае ошибки
             self.setGeometry(0, 0, 800, 600)
             print(f"[ScreenSelector] Fallback widget geometry: {self.geometry().x()},{self.geometry().y()},{self.geometry().width()},{self.geometry().height()}",
                  file=sys.stderr, flush=True)


        # Сбрасываем состояние выделения при каждом показе
        self._is_selecting = False
        self._start_pos = QPoint()
        self._end_pos = QPoint()
        self._selection_rect = QRect()
        self.update() # Запрашиваем перерисовку

        # Активируем окно и выводим его на передний план
        self.activateWindow()
        self.raise_()
        super().showEvent(event) # Вызываем базовый обработчик

    def paintEvent(self, event):
        """Обработчик события отрисовки виджета."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing) # Сглаживание

        # Заливаем весь виджет полупрозрачным серым цветом
        painter.fillRect(self.rect(), self._brush_color)

        # Если идет выделение и прямоугольник не пуст
        if self._is_selecting and not self._selection_rect.isNull():
            # Устанавливаем режим композиции "Очистка"
            # Это делает область, где будет отрисован следующий примитив, полностью прозрачной
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear
            )
            # Заливаем область выделения прозрачным цветом (делает ее "дырой" в сером фоне)
            painter.fillRect(self._selection_rect, Qt.GlobalColor.transparent)

            # Возвращаем режим композиции "Поверх источника"
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )

            # Настраиваем перо для рисования рамки
            pen = QPen(
                self._pen_color, self._pen_width, Qt.PenStyle.SolidLine
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush) # Без заливки

            # Рисуем рамку вокруг выделенной области
            painter.drawRect(self._selection_rect)

    def mousePressEvent(self, event):
        """Обработчик нажатия кнопки мыши."""
        # Нажатие ЛКМ начинает выделение
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_pos = event.pos() # Сохраняем начальную позицию
            self._end_pos = event.pos() # Конечная позиция пока совпадает
            self._is_selecting = True # Включаем флаг выделения
            self._update_selection_rect() # Обновляем прямоугольник выделения
            print(f"[ScreenSelector] Mouse Press at {self._start_pos.x()},{self._start_pos.y()}",
                  file=sys.stderr, flush=True)
        # Нажатие ПКМ отменяет выделение
        elif event.button() == Qt.MouseButton.RightButton:
            print("[ScreenSelector] Right click - Cancelled", flush=True)
            self.selection_cancelled.emit() # Отправляем сигнал отмены
            self.close() # Закрываем виджет

    def mouseMoveEvent(self, event):
        """Обработчик движения мыши."""
        # Если идет выделение
        if self._is_selecting:
            self._end_pos = event.pos() # Обновляем конечную позицию
            self._update_selection_rect() # Обновляем прямоугольник выделения
            self.update() # Запрашиваем перерисовку для отображения текущего выделения

    def mouseReleaseEvent(self, event):
        """Обработчик отпускания кнопки мыши."""
        # Отпускание ЛКМ завершает выделение
        if event.button() == Qt.MouseButton.LeftButton and self._is_selecting:
            self._is_selecting = False # Выключаем флаг выделения
            self._update_selection_rect() # Финальное обновление прямоугольника
            # Нормализуем прямоугольник (углы могут быть перепутаны, если пользователь тянул вверх или влево)
            final_rect = self._selection_rect.normalized()
            print(f"[ScreenSelector] Mouse Release - Raw Rect: {self._selection_rect.x()},{self._selection_rect.y()},{self._selection_rect.width()},{self._selection_rect.height()}",
                  file=sys.stderr, flush=True)
            print(f"[ScreenSelector] Mouse Release - Final (Normalized) Rect: {final_rect.x()},{final_rect.y()},{final_rect.width()},{final_rect.height()}",
                  file=sys.stderr, flush=True)

            # Проверяем, достаточно ли большое выделение
            min_size = 5 # Минимальный размер в пикселях
            if final_rect.width() > min_size and final_rect.height() > min_size:
                # Получаем координаты относительно виртуального рабочего стола (который является self.rect())
                # Поскольку self занимает весь виртуальный рабочий стол с координатами 0,0
                # (ну, или X,Y если мониторы не начинаются с 0,0), то координаты event.pos()
                # уже являются глобальными координатами экрана.
                # self.mapToGlobal(self._start_pos) вернет просто _start_pos, т.к. self является окном верхнего уровня
                # и его top-left (0,0) в системе координат виджета соответствует его top-left на экране.
                # Поэтому final_rect уже содержит глобальные координаты.
                self.area_selected.emit(final_rect) # Отправляем сигнал с финальным прямоугольником
                print(f"[ScreenSelector] Emitting area_selected: {final_rect.x()},{final_rect.y()},{final_rect.width()},{final_rect.height()}",
                      file=sys.stderr, flush=True)

            else:
                print(f"[ScreenSelector] Selection too small (<{min_size}x{min_size} px) - Cancelled.",
                      file=sys.stderr, flush=True)
                self.selection_cancelled.emit() # Отправляем сигнал отмены

            # Закрываем виджет после завершения выделения (успех или отмена)
            self.close()

    def keyPressEvent(self, event):
        """Обработчик нажатия клавиши клавиатуры."""
        # Нажатие ESC отменяет выделение
        if event.key() == Qt.Key.Key_Escape:
            print("[ScreenSelector] ESC pressed - Cancelled", flush=True)
            self.selection_cancelled.emit() # Отправляем сигнал отмены
            self.close() # Закрываем виджет
        else:
            # Для других клавиш вызываем базовый обработчик
            super().keyPressEvent(event)

    def _update_selection_rect(self):
        """Обновляет `self._selection_rect` из начальной и конечной позиций."""
        self._selection_rect = QRect(
            self._start_pos, self._end_pos
        ).normalized() # Нормализация гарантирует положительные ширину/высоту


    def closeEvent(self, event):
        """Обработчик события закрытия виджета."""
        print("[ScreenSelector] Close event", flush=True)
        # Восстанавливаем стандартный курсор при закрытии
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # self.deleteLater() # PyQt6 часто управляет жизнью виджетов, но явное удаление может помочь
        super().closeEvent(event) # Вызываем базовый обработчик


# --- END OF FILE screen_selector.py ---