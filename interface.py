
import os

from PyQt6.QtCore import (QMetaObject, QPoint, QRect, QSize, Qt, QTimer,
                          pyqtSlot)
from PyQt6.QtGui import QColor, QIcon, QIntValidator, QPixmap, QFont, QCursor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog,
                             QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QSizePolicy, QSpinBox,
                             QToolTip, QVBoxLayout, QWidget)

from constants import (ADD_ITEM_HOTKEY, DEFAULT_ITEM_ENABLED,
                       DEFAULT_ITEM_MAX_PRICE, DEFAULT_ITEM_QUANTITY,
                       MAIN_WINDOW_HEIGHT, MAIN_WINDOW_WIDTH,
                       STOP_MONITORING_HOTKEY, TEMPLATE_FOLDER)


# --- Диалог редактирования товара ---
class ItemEditDialog(QDialog):
    """Диалоговое окно для редактирования параметров выбранного товара."""

    def __init__(self, item_data: dict, parent=None):
        super().__init__(parent)
        item_name = item_data.get("name", "Неизвестно")
        # Ограничиваем длину имени для заголовка окна
        display_name = item_name if len(item_name) <= 40 else item_name[:37] + "..."
        self.setWindowTitle(f"Редактировать: {display_name}")
        self.setMinimumWidth(350)
        self.item_data = item_data.copy() # Работаем с копией данных
        self._create_widgets()
        self._populate_fields()
        self._setup_layout()
        self._connect_signals()

    def _create_widgets(self):
        # Отображаемое имя товара без ограничения длины для информации
        item_name_full = self.item_data.get("name", "Неизвестно")
        self.nameLabel = QLabel(f"<b>{item_name_full}</b>")
        self.nameLabel.setWordWrap(True) # Перенос текста, если имя длинное
        self.templateLabel = QLabel("Шаблон:")
        self.templateIconLabel = QLabel()
        self.templateIconLabel.setFixedSize(120, 40) # Увеличено для лучшей видимости
        self.templateIconLabel.setStyleSheet(
            "border: 1px solid gray; background-color: #f0f0f0;"
        )
        self.templateIconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Добавление шрифта для сообщения "Нет файла..."
        font = QFont(); font.setPointSize(8); self.templateIconLabel.setFont(font)


        self.enabledCheckbox = QCheckBox("Поиск включен")
        self.enabledCheckbox.setToolTip(
            "Включить/выключить автоматический поиск и покупку этого товара."
        )

        self.maxPriceEdit = QLineEdit()
        self.maxPriceEdit.setPlaceholderText("0 (без лимита)")
        self.maxPriceEdit.setToolTip(
            "Максимальная цена, за которую будет куплен товар.\n"
            "Установите 0, чтобы покупать по любой цене."
        )
        # Используем QIntValidator с ограничением
        self.maxPriceEdit.setValidator(QIntValidator(0, 2_000_000_000, self)) # Достаточно большое число

        self.quantitySpinBox = QSpinBox()
        self.quantitySpinBox.setMinimum(1)
        self.quantitySpinBox.setMaximum(99999) # Увеличено
        self.quantitySpinBox.setToolTip(
            "Сколько штук этого товара нужно купить (цель)."
        )

        # Счетчик текущего количества (только для отображения)
        self.boughtCountLabel = QLabel()
        self.boughtCountLabel.setToolTip("Текущее количество купленного товара (сброс при перезапуске).")


        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )

    def _populate_fields(self):
        template_path = self.item_data.get("template_path")
        if template_path and os.path.exists(template_path):
            pixmap = QPixmap(template_path)
            if not pixmap.isNull():
                # Масштабирование с сохранением пропорций
                self.templateIconLabel.setPixmap(
                    pixmap.scaled(
                        self.templateIconLabel.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.templateIconLabel.setStyleSheet(
                    "border: 1px solid gray; background-color: #f0f0f0;"
                ) # Сбросить стиль ошибки/предупреждения
            else:
                self.templateIconLabel.setText("Ошибка\nзагрузки")
                self.templateIconLabel.setStyleSheet(
                    "border: 1px solid red; color: red; "
                    "background-color: #f0f0f0; font-size: 8pt;"
                )
        else:
            self.templateIconLabel.setText("Нет файла\nшаблона")
            self.templateIconLabel.setStyleSheet(
                "border: 1px solid orange; color: orange; "
                "background-color: #f0f0f0; font-size: 8pt;"
            )


        self.enabledCheckbox.setChecked(
            self.item_data.get("enabled", DEFAULT_ITEM_ENABLED)
        )
        price_val = self.item_data.get("max_price", DEFAULT_ITEM_MAX_PRICE)
        # Отображаем 0 как "0" даже если значение по умолчанию 0
        self.maxPriceEdit.setText(str(price_val))

        self.quantitySpinBox.setValue(
            self.item_data.get("quantity", DEFAULT_ITEM_QUANTITY)
        )

        # Отображение текущего счетчика
        bought_count = self.item_data.get("bought_count", 0)
        self.boughtCountLabel.setText(str(bought_count))


    def _setup_layout(self):
        mainLayout = QVBoxLayout(self)
        formLayout = QFormLayout()

        # Название товара - отдельный макет для переноса текста
        nameLayout = QHBoxLayout()
        nameLayout.addWidget(self.nameLabel)
        nameLayout.addStretch()
        formLayout.addRow("Название:", nameLayout)

        # Шаблон - макет для иконки
        templateLayout = QHBoxLayout()
        templateLayout.addWidget(self.templateIconLabel)
        templateLayout.addStretch()
        formLayout.addRow(self.templateLabel, templateLayout)

        formLayout.addRow(self.enabledCheckbox) # Чекбокс сам по себе

        formLayout.addRow("Макс. цена ($):", self.maxPriceEdit)
        formLayout.addRow("Купить кол-во:", self.quantitySpinBox)
        formLayout.addRow("Куплено (текущий запуск):", self.boughtCountLabel) # Добавление счетчика


        mainLayout.addLayout(formLayout)
        mainLayout.addWidget(self.buttonBox)

    def _connect_signals(self):
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    def get_updated_data(self) -> dict:
        """Возвращает словарь с обновленными данными."""
        try:
            # Обработка введенной цены, пустая строка -> 0
            price_text = self.maxPriceEdit.text().strip()
            max_price = int(price_text) if price_text.isdigit() else 0 # Проверяем, что введены только цифры
            if max_price < 0: max_price = 0 # На всякий случай
        except ValueError:
            max_price = 0 # Если валидатор пропустил что-то нечисловое, сброс
        return {
            "enabled": self.enabledCheckbox.isChecked(),
            "max_price": max_price,
            "quantity": self.quantitySpinBox.value(),
            # purchased_count НЕ редактируется через диалог
        }


# --- Основное окно приложения ---
class MainWindow(QWidget):
    """Главное окно приложения Market Helper."""

    # logic: BotLogic # Добавление типа для подсказок

    def __init__(self, logic, parent=None):
        super().__init__(parent)
        self.logic = logic
        self.initUI()
        self.connect_signals()
        # Изначальное обновление списка и состояния контролов
        self.update_item_list(self.logic.get_item_data_for_display())
        # Используем invokeMethod для выполнения после обработки событий инициализации GUI
        QMetaObject.invokeMethod(
            self, "_initial_ui_state", Qt.ConnectionType.QueuedConnection
        )

    @pyqtSlot()
    def _initial_ui_state(self):
        """Устанавливает начальное состояние UI после его полной инициализации."""
        self.enable_controls(True) # Сброс состояния контролов
        self._update_start_button_state() # Обновление состояния кнопки Старт


    def initUI(self):
        """Инициализация элементов пользовательского интерфейса."""
        self.setWindowTitle("GTA V RP Market Helper")
        # Держим окно поверх других, но позволяем взаимодействовать с другими
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )
        # Устанавливаем начальный размер окна
        self.setGeometry(
            100, 100, MAIN_WINDOW_WIDTH, MAIN_WINDOW_HEIGHT
        )
        # Добавляем иконку (если есть)
        icon_path = os.path.join(self.logic.BASE_DIR, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
             icon_path_png = os.path.join(self.logic.BASE_DIR, "icon.png")
             if os.path.exists(icon_path_png):
                 self.setWindowIcon(QIcon(icon_path_png))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10) # Отступы
        main_layout.setSpacing(5) # Меньшее расстояние между элементами

        self._setup_management_panel(main_layout)
        self._setup_item_list(main_layout)
        self._setup_search_panel(main_layout)
        self._setup_status_bar(main_layout)

        self.setLayout(main_layout)

    def _setup_management_panel(self, parent_layout: QVBoxLayout):
        """Настраивает панель управления товарами (добавить/удалить/настройки)."""
        mgmt_layout = QHBoxLayout()
        mgmt_layout.setSpacing(5)

        # Кнопка добавления товара
        add_tooltip = (
            f"Начать выделение области названия товара для добавления.\n"
            f"(Клавиша: '{ADD_ITEM_HOTKEY.upper()}')"
        )
        self.addItemButton = QPushButton(
            f"Добавить ({ADD_ITEM_HOTKEY.upper()})"
        )
        self.addItemButton.setToolTip(add_tooltip)
        self.addItemButton.setCursor(Qt.CursorShape.PointingHandCursor) # Курсор руки

        # Кнопка удаления товара
        self.removeItemButton = QPushButton("Удалить")
        self.removeItemButton.setToolTip("Удалить выбранный товар и его шаблон.")
        self.removeItemButton.setEnabled(False) # Изначально неактивна
        self.removeItemButton.setCursor(Qt.CursorShape.PointingHandCursor)


        # Чекбокс игнорирования аренды
        self.ignoreRentCheckbox = QCheckBox("Игнор. 'Аренда'")
        self.ignoreRentCheckbox.setToolTip(
            "Не добавлять товары, названия которых начинаются с 'Аренда' или 'Rent'."
        )
        # Устанавливаем состояние чекбокса из логики при запуске
        self.ignoreRentCheckbox.setChecked(self.logic.ignore_rent)
        self.ignoreRentCheckbox.setCursor(Qt.CursorShape.PointingHandCursor)

        mgmt_layout.addWidget(self.addItemButton)
        mgmt_layout.addWidget(self.removeItemButton)
        mgmt_layout.addStretch() # Расширяемое пространство
        mgmt_layout.addWidget(self.ignoreRentCheckbox)

        parent_layout.addLayout(mgmt_layout)

    def _setup_item_list(self, parent_layout: QVBoxLayout):
        """Настраивает виджет списка товаров."""
        self.itemListLabel = QLabel("Товары (Двойной клик - ред.):")
        self.itemListWidget = QListWidget()
        self.itemListWidget.setToolTip(
            "Список товаров для поиска.\n"
            "Галочка слева - включить/выключить поиск для товара.\n"
            "Двойной клик по товару - редактировать параметры (кол-во, макс. цена).\n"
            "Наведите курсор для деталей."
        )
        self.itemListWidget.setMouseTracking(True) # Включаем отслеживание мыши для тултипов
        self.itemListWidget.setAlternatingRowColors(True) # Чередование цветов строк
        self.itemListWidget.setCursor(Qt.CursorShape.PointingHandCursor)


        parent_layout.addWidget(self.itemListLabel)
        parent_layout.addWidget(self.itemListWidget, 1) # Растягиваем список

    def _setup_search_panel(self, parent_layout: QVBoxLayout):
        """Настраивает панель управления поиском (старт/стоп)."""
        search_layout = QHBoxLayout()
        search_layout.setSpacing(5)

        # Кнопка "Начать АВТО-поиск"
        start_tooltip = (
            "Начать поиск и выполнение действий (клик + ESC)\n"
            "для всех отмеченных товаров, у которых есть шаблон."
        )
        self.startButton = QPushButton("Начать АВТО-поиск")
        self.startButton.setToolTip(start_tooltip)
        self.startButton.setEnabled(False) # Изначально неактивна
        self.startButton.setCursor(Qt.CursorShape.PointingHandCursor)


        # Кнопка "Стоп"
        stop_tooltip = (
            f"Остановить текущий процесс поиска.\n"
            f"(Клавиша: Numpad '{STOP_MONITORING_HOTKEY}')"
        )
        self.stopButton = QPushButton("Стоп")
        self.stopButton.setToolTip(stop_tooltip)
        self.stopButton.setEnabled(False) # Изначально неактивна
        self.stopButton.setCursor(Qt.CursorShape.PointingHandCursor)


        search_layout.addStretch() # Расширяемое пространство
        search_layout.addWidget(self.startButton)
        search_layout.addWidget(self.stopButton)

        parent_layout.addLayout(search_layout)

    def _setup_status_bar(self, parent_layout: QVBoxLayout):
        """Настраивает строку статуса."""
        self.statusBar = QLabel("Инициализация...") # Начальный текст статуса
        status_style = (
            "QLabel { padding: 3px; background-color: #f0f0f0; "
            "border-top: 1px solid #c0c0c0; font-size: 9pt; }"
        )
        self.statusBar.setStyleSheet(status_style)
        self.statusBar.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) # Выравнивание текста
        parent_layout.addWidget(self.statusBar)

    def connect_signals(self):
        """Подключает сигналы GUI к слотам логики и наоборот."""
        # Управление товарами (GUI -> Logic)
        self.addItemButton.clicked.connect(self.logic.trigger_area_selection)
        self.removeItemButton.clicked.connect(self._on_remove_item)
        # Сигналы списка товаров
        self.itemListWidget.currentItemChanged.connect(
            self._on_item_selection_changed
        )
        self.itemListWidget.itemDoubleClicked.connect(self._open_item_editor)
        self.itemListWidget.itemChanged.connect(self._on_item_check_changed)
        self.itemListWidget.itemEntered.connect(self.show_item_tooltip) # Сигнал для тултипа при наведении

        # Чекбокс игнорирования аренды (GUI -> Logic)
        self.ignoreRentCheckbox.stateChanged.connect(
            self.logic.set_ignore_rent_state
        )

        # Управление поиском (GUI -> Logic)
        self.startButton.clicked.connect(self._on_start_monitoring)
        self.stopButton.clicked.connect(self.logic.stop_monitoring)

        # Сигналы от BotLogic к Interface (Logic -> GUI)
        self.logic.signal_update_status.connect(self.update_status)
        self.logic.signal_enable_controls.connect(self.enable_controls)
        self.logic.signal_update_item_list.connect(self.update_item_list)
        self.logic.signal_action_performed.connect(self._on_action_performed)
        self.logic.signal_monitoring_stopped.connect(
            self._on_monitoring_stopped
        )
        # Сигнал для ошибки инициализации логики (если она не привела к полному краху)
        # self.logic.signal_init_error.connect(self._on_logic_init_error) # Если бы был такой сигнал

    # --- Слоты-обработчики событий интерфейса (реагируют на действия пользователя) ---
    @pyqtSlot()
    def _on_remove_item(self):
        """Обработчик клика по кнопке 'Удалить'."""
        item_widget = self.itemListWidget.currentItem()
        if not item_widget:
            return # Нет выбранного элемента
        item_data = item_widget.data(Qt.ItemDataRole.UserRole)
        if not item_data or "name" not in item_data:
            # Ошибка в данных элемента списка
            QMessageBox.critical(self, "Ошибка данных", "Некорректные данные выбранного товара.")
            return
        name = item_data.get("name", "N/A")

        # Подтверждение удаления
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Вы уверены, что хотите удалить товар '{name}' и его шаблон?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No, # По умолчанию выбрано "Нет"
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Передаем запрос на удаление в логику
            self.logic.remove_item(name)

    @pyqtSlot(QListWidgetItem, QListWidgetItem)
    def _on_item_selection_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ):
        """Обработчик смены выбранного элемента в списке."""
        # Кнопка удаления активна только если что-то выбрано И процесс не запущен
        can_remove = (
            current is not None
            and not self.logic.monitoring_active
            and not self.logic.is_selecting_area
        )
        self.removeItemButton.setEnabled(can_remove)

    @pyqtSlot(QListWidgetItem)
    def _open_item_editor(self, item_widget: QListWidgetItem):
        """Обработчик двойного клика по элементу списка - открывает редактор."""
        if not item_widget:
            return # Нет элемента

        # Проверяем состояние приложения - нельзя редактировать во время поиска/выделения
        if self.logic.monitoring_active or self.logic.is_selecting_area:
            self.update_status("Остановите процесс для редактирования.")
            QMessageBox.warning(
                self,
                "Действие недоступно",
                "Сначала остановите поиск или режим выделения.",
            )
            return

        item_data = item_widget.data(Qt.ItemDataRole.UserRole)
        if not item_data or "name" not in item_data:
            QMessageBox.critical(self, "Ошибка данных", "Некорректные данные выбранного товара.")
            return

        # Создаем и показываем диалог редактирования
        dialog = ItemEditDialog(item_data, self)
        if dialog.exec(): # exec() блокирует выполнение до закрытия диалога
            # Получаем обновленные данные из диалога, если пользователь нажал OK
            updated_data = dialog.get_updated_data()
            # Передаем обновленные данные в логику для сохранения и обновления
            self.logic.update_item_data(item_data.get("name"), updated_data)

    @pyqtSlot(QListWidgetItem)
    def _on_item_check_changed(self, item_widget: QListWidgetItem):
        """Обработчик изменения состояния чекбокса элемента списка."""
        if not item_widget:
            return
        # Блокируем сигналы списка, чтобы избежать рекурсии или лишних вызовов
        # при программном изменении состояния в _style_list_item
        self.itemListWidget.blockSignals(True)
        try:
            item_data = item_widget.data(Qt.ItemDataRole.UserRole)
            if not item_data or not isinstance(item_data, dict) or "name" not in item_data:
                return # Некорректные данные

            item_name = item_data.get("name")
            is_enabled = item_widget.checkState() == Qt.CheckState.Checked

            # Обновляем состояние "включен" в логике
            self.logic.set_item_enabled_status(item_name, is_enabled)

            # Получаем актуальные данные из логики (включая bought_count, который не в UI редактируется)
            # Это нужно, чтобы _style_list_item корректно отображал все статусы
            updated_item_data = self.logic.get_item_data_by_name(item_name)
            if updated_item_data:
                 # Обновляем UserRole данные в QListWidgetItem для синхронизации
                 item_widget.setData(Qt.ItemDataRole.UserRole, updated_item_data.copy())
                 # Перерисовываем элемент с учетом нового состояния и других данных
                 self._style_list_item(item_widget, updated_item_data)

            # Обновляем состояние кнопки "Начать"
            self._update_start_button_state()

        finally:
            # Разблокируем сигналы списка
            self.itemListWidget.blockSignals(False)


    def _on_start_monitoring(self):
        """Обработчик клика по кнопке 'Начать АВТО-поиск'."""
        # Перед запуском проверяем, есть ли вообще активные товары с шаблонами
        enabled_items_data = self._get_enabled_items_with_templates()

        if not enabled_items_data:
            QMessageBox.warning(
                self,
                "Нет товаров для поиска",
                "Выберите хотя бы один товар и убедитесь, что у него есть шаблон файла (.png)."
            )
            self.update_status("Запуск невозможен: нет активных товаров с шаблонами.")
            return

        # Проверка наличия шаблонов для отмеченных товаров (повторная, но с сообщением)
        missing_templates = [
            d.get("name", "N/A")
            for d in enabled_items_data
            if not d.get("template_path") or not os.path.exists(d.get("template_path"))
        ]

        if missing_templates:
            msg = (
                f"Внимание!\nДля следующих товаров включен поиск, но отсутствуют файлы шаблонов:\n\n"
                f" - {'\n - '.join(missing_templates)}\n\n"
                f"Эти товары будут проигнорированы при поиске.\nПродолжить поиск только для товаров с шаблонами?"
            )
            reply = QMessageBox.question(
                self,
                "Отсутствуют шаблоны",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes, # По умолчанию "Да"
            )
            if reply == QMessageBox.StandardButton.No:
                self.update_status("Запуск отменен пользователем.")
                return # Отменяем запуск

        # Если дошли сюда, значит есть хотя бы один валидный товар или пользователь согласился
        # Проверяем, что логика готова к запуску (ресурсы инициализированы)
        if not hasattr(self.logic, 'initialized_ok') or not self.logic.initialized_ok:
            QMessageBox.critical(self, "Ошибка инициализации", "Система не инициализирована корректно. Перезапустите приложение.\nСм. лог файл.")
            self.update_status("Ошибка инициализации системы.")
            return

        # Передаем команду на старт в логику
        self.logic.start_monitoring()


    def _get_enabled_items_with_templates(self) -> list:
        """Возвращает список данных товаров, которые включены и имеют существующий файл шаблона."""
        enabled_valid_items = []
        for i in range(self.itemListWidget.count()):
            item_widget = self.itemListWidget.item(i)
            if item_widget.checkState() == Qt.CheckState.Checked:
                item_data = item_widget.data(Qt.ItemDataRole.UserRole)
                if item_data and isinstance(item_data, dict):
                    path = item_data.get("template_path")
                    if path and os.path.exists(path):
                        enabled_valid_items.append(item_data)
                    # else: Логирование предупреждения уже происходит в BotLogic при загрузке/валидации
        return enabled_valid_items


    # --- Слоты для обработки сигналов от BotLogic (реагируют на события логики) ---
    @pyqtSlot(str)
    def update_status(self, status: str):
        """Обновляет текст в строке статуса."""
        self.statusBar.setText(status)

    @pyqtSlot(list)
    def update_item_list(self, items_data: list):
        """Обновляет содержимое списка товаров в GUI."""
        # Сохраняем текущий выбранный элемент по имени, чтобы восстановить выбор после обновления
        selected_name = None
        current_item = self.itemListWidget.currentItem()
        if current_item:
            data = current_item.data(Qt.ItemDataRole.UserRole)
            if data and isinstance(data, dict):
                selected_name = data.get("name")

        # Блокируем сигналы списка перед его очисткой и наполнением
        self.itemListWidget.blockSignals(True)
        self.itemListWidget.clear()

        # Сортируем товары по имени для удобства
        sorted_items = sorted(items_data, key=lambda x: x.get("name", "").lower())

        new_selected_item = None # Для сохранения ссылки на новый выбранный элемент
        for item_data in sorted_items:
            name = item_data.get("name", "N/A")
            # Создаем QListWidgetItem
            list_item = QListWidgetItem(name)

            # Устанавливаем флаги: возможность ставить галочку, выбирать, быть активным
            flags = (
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
            )
            list_item.setFlags(list_item.flags() | flags)

            # Устанавливаем состояние чекбокса
            is_enabled = item_data.get("enabled", DEFAULT_ITEM_ENABLED)
            list_item.setCheckState(
                Qt.CheckState.Checked if is_enabled else Qt.CheckState.Unchecked
            )

            # Сохраняем полные данные товара в UserRole для доступа при взаимодействии
            list_item.setData(Qt.ItemDataRole.UserRole, item_data.copy())

            # Применяем стили и тултипы
            self._style_list_item(list_item, item_data)

            # Добавляем элемент в список
            self.itemListWidget.addItem(list_item)

            # Если это был выбранный ранее элемент, сохраняем на него ссылку
            if name == selected_name:
                new_selected_item = list_item

        # Разблокируем сигналы списка
        self.itemListWidget.blockSignals(False)

        # Восстанавливаем выбор или выбираем первый элемент, если список не пуст
        if new_selected_item:
            self.itemListWidget.setCurrentItem(new_selected_item)
        elif self.itemListWidget.count() > 0:
             # Сохраняем текущую строку, чтобы не прыгать на 0, если список просто обновился
            row = self.itemListWidget.currentRow()
            if row < 0 or row >= self.itemListWidget.count():
                 row = 0 # Если текущая строка невалидна, выбираем 0
            self.itemListWidget.setCurrentRow(row)
             # Вызываем обработчик смены выбора вручную, т.к.setCurrentRow может не вызвать сигнал
            self._on_item_selection_changed(self.itemListWidget.currentItem(), None)


        # После обновления списка, обновляем состояние кнопки "Начать"
        self._update_start_button_state()


    def _style_list_item(self, list_item: QListWidgetItem, item_data: dict):
        """Применяет стили (цвет) и тултип к элементу списка на основе данных товара."""
        is_enabled = item_data.get("enabled", False)
        path = item_data.get("template_path")
        # Проверяем существование файла шаблона
        template_exists = path and os.path.exists(path)

        # Формируем текст тултипа
        tip_lines = []
        tip_lines.append(f"<b>{item_data.get('name', 'N/A')}</b>") # Название жирным
        tip_lines.append("") # Пустая строка для отступа

        # Статус шаблона
        if template_exists:
            tip_lines.append("Шаблон: <span style='color:green;'>✅ Есть</span>")
        else:
            tip_lines.append("Шаблон: <span style='color:red;'>❌ НЕТ!</span>")

        # Статус поиска
        if is_enabled:
            tip_lines.append("Поиск: <span style='color:green;'>▶️ Включен</span>")
        else:
             # Серое для выключенных
            tip_lines.append("Поиск: <span style='color:gray;'>⏹️ Выключен</span>")

        # Параметры товара
        price = item_data.get("max_price", 0)
        tip_lines.append(f"Макс. цена: {price}${' (Без лимита)' if price == 0 else ''}")
        tip_lines.append(f"Цель: {item_data.get('quantity', 1)} шт.")
        tip_lines.append(f"Куплено (текущий запуск): {item_data.get('bought_count', 0)}")


        # Устанавливаем тултип (можно использовать HTML)
        list_item.setToolTip("<br>".join(tip_lines))

        # Устанавливаем цвет текста элемента
        if not template_exists:
            # Красный, если нет шаблона
            list_item.setForeground(QColor("red"))
        elif not is_enabled:
            # Серый, если выключен поиск (но шаблон есть)
            list_item.setForeground(QColor("gray"))
        else:
            # Черный/стандартный, если включен и шаблон есть
            list_item.setForeground(QColor("black"))


    @pyqtSlot(QListWidgetItem)
    def show_item_tooltip(self, item: QListWidgetItem):
        """Показывает тултип для элемента списка при наведении."""
        if item and item.toolTip():
            # Определяем позицию для тултипа справа от элемента
            rect = self.itemListWidget.visualItemRect(item)
            if rect.isValid():
                # Мапим координаты прямоугольника элемента из координат виджета списка в глобальные координаты экрана
                # Показываем тултип справа по центру элемента
                tooltip_pos = self.itemListWidget.mapToGlobal(rect.center() + QPoint(rect.width() // 2, 0))
                QToolTip.showText(
                    tooltip_pos,
                    item.toolTip(),
                    self.itemListWidget, # Виджет-родитель для тултипа
                    rect, # Прямоугольник элемента, чтобы тултип исчезал при уходе мыши
                    3000 # Время отображения тултипа в мс
                )

    def _update_start_button_state(self):
        """Обновляет активность кнопки 'Начать АВТО-поиск'."""
        # Кнопка активна, если:
        # 1. Нет активного мониторинга И нет режима выделения области.
        # 2. Есть хотя бы один товар в списке, который включен И имеет существующий файл шаблона.
        is_monitoring = self.logic.monitoring_active
        is_selecting = self.logic.is_selecting_area

        # Проверяем наличие активных товаров с шаблонами
        has_enabled_valid_items = len(self._get_enabled_items_with_templates()) > 0

        # Устанавливаем активность кнопки
        self.startButton.setEnabled(
            not is_monitoring and not is_selecting and has_enabled_valid_items
        )


    @pyqtSlot(bool)
    def enable_controls(self, enable: bool):
        """Включает или выключает основные контролы интерфейса."""
        # Это слот вызывается из логики для синхронизации состояния UI
        # Используем текущие состояния мониторинга и выделения из логики
        is_monitoring = self.logic.monitoring_active
        is_selecting = self.logic.is_selecting_area

        # Кнопка Стоп активна только если мониторинг запущен
        self.stopButton.setEnabled(is_monitoring)

        # Управление товарами (Добавить, Удалить, Список, Игнор. Аренда) активны
        # только если НЕ запущен мониторинг И НЕ режим выделения
        can_manage = not is_monitoring and not is_selecting
        self.addItemButton.setEnabled(can_manage)
        self.itemListWidget.setEnabled(can_manage)
        self.ignoreRentCheckbox.setEnabled(can_manage)

        # Кнопка Удалить активна только если можно управлять И что-то выбрано в списке
        item_selected = self.itemListWidget.currentItem() is not None
        self.removeItemButton.setEnabled(can_manage and item_selected)

        # Кнопка Старт обновляется отдельно функцией _update_start_button_state,
        # т.к. зависит еще и от состояния списка товаров.
        self._update_start_button_state()

        # Обновление курсора для MainWindow
        if is_selecting:
             # Курсор поменяется в ScreenSelectionWidget, но можно сбросить здесь
             # self.setCursor(Qt.CursorShape.ArrowCursor)
             pass # Курсор будет установлен в ScreenSelectionWidget
        elif is_monitoring:
             self.setCursor(Qt.CursorShape.WaitCursor) # Курсор ожидания
        else:
             self.setCursor(Qt.CursorShape.ArrowCursor) # Стандартный курсор

        # Очистка статуса через некоторое время, если нет важного сообщения
        if can_manage: # Если контролы разблокированы (вне активных режимов)
            current_status = self.statusBar.text()
            # Определяем, является ли текущий статус "важным" (ошибка, результат действия и т.п.)
            important_keywords = [
                "ошибка", "куплено", "добавлено", "удалено", "обновлено",
                "проигнор", "достигнуты", "отменен", "уже есть",
                "остановка", "поиск...", "выделение...", "обработка...",
                "действие", "готов."
            ]
            # Проверяем, содержит ли текущий статус одно из важных ключевых слов (без учета регистра)
            is_important_status = any(kw in current_status.lower() for kw in important_keywords)

            # Если статус не является важным И не равен "Готов."
            if not is_important_status and current_status != "Готов.":
                # Сбрасываем статус на "Готов." через 2.5 секунды
                QTimer.singleShot(
                    2500, lambda: self.update_status("Готов.")
                )

    @pyqtSlot(str, int, int)
    def _on_action_performed(
        self, item_name, price, new_total_bought_count
    ):
        """Обработчик сигнала о выполненном действии для товара."""
        # Воспроизводим системный звук для оповещения
        QApplication.beep()

        # Обновляем статус товара в списке GUI
        for i in range(self.itemListWidget.count()):
            item_widget = self.itemListWidget.item(i)
            item_data = item_widget.data(Qt.ItemDataRole.UserRole)
            if item_data and item_data.get("name") == item_name:
                # Обновляем счетчик купленного в данных элемента списка
                item_data["bought_count"] = new_total_bought_count
                item_widget.setData(Qt.ItemDataRole.UserRole, item_data)
                # Обновляем стиль и тултип элемента списка
                self._style_list_item(item_widget, item_data)
                # Делаем элемент текущим для визуального выделения
                self.itemListWidget.setCurrentItem(item_widget)
                # Прокручиваем список, чтобы увидеть этот элемент
                self.itemListWidget.scrollToItem(item_widget, QListWidget.ScrollHint.EnsureVisible)
                break # Нашли и обновили, выходим из цикла

        # Обновляем строку статуса
        # (Статус уже устанавливается в BotLogic перед отправкой сигнала,
        # но можно добавить дополнительное здесь, если нужно)
        # self.update_status(f"Действие: {item_name} ({new_total_bought_count}) за {price}$")


    @pyqtSlot(bool)
    def _on_monitoring_stopped(self, stopped_by_target: bool):
        """Обработчик сигнала об остановке мониторинга."""
        # Логика уже установила статус и обновила состояние controls
        # self.update_status("Поиск остановлен." if not stopped_by_target else "Все цели достигнуты!")
        # self.enable_controls(True) # Уже вызвано в BotLogic перед этим сигналом

        # Опционально: показать сообщение, если остановка произошла по достижению целей
        if stopped_by_target:
            QMessageBox.information(
                self,
                "Поиск завершен",
                "Все цели для активных товаров достигнуты.\nАвтоматический поиск остановлен."
            )

    # @pyqtSlot(str)
    # def _on_logic_init_error(self, error_msg):
    #     """Обработчик сигнала о критической ошибке инициализации логики."""
    #     # Этот слот будет вызван, если BotLogic не сможет инициализироваться
    #     # (например, MSS или OCR), и BotLogic отправит такой сигнал
    #     # (в текущей версии BotLogic при критических ошибках он сам вызывает
    #     # global_except_hook или показывает QMessageBox и завершает работу,
    #     # так что этот слот может быть не нужен или использоваться для
    #     # менее критичных ошибок инициализации).
    #     QMessageBox.critical(self, "Ошибка инициализации", f"Не удалось инициализировать логику приложения:\n{error_msg}\nПриложение будет закрыто.")
    #     QApplication.quit() # Завершаем приложение

    def closeEvent(self, event):
        """Обработчик события закрытия главного окна."""
        # Перед закрытием окна, запускаем процедуру очистки в логике
        # Эта процедура должна остановить Worker, освободить ресурсы и сохранить данные
        print("MainWindow: closeEvent - Запуск очистки логики...", flush=True)
        self.logic.cleanup() # Запускаем очистку

        # Позволяем событию закрытия произойти
        event.accept()
        print("MainWindow: closeEvent - Событие принято. Окно будет закрыто.", flush=True)

# --- END OF FILE interface.py ---