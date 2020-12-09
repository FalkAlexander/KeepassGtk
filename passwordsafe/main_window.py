# SPDX-License-Identifier: GPL-3.0-only
import logging
import os
import threading
from gettext import gettext as _
from typing import List, Optional
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Handy
from gi.repository.GdkPixbuf import Pixbuf

import passwordsafe.config_manager
from passwordsafe.container_page import ContainerPage
from passwordsafe.create_database import CreateDatabase
from passwordsafe.database_manager import DatabaseManager
from passwordsafe.error_info_bar import ErrorInfoBar
from passwordsafe.unlock_database import UnlockDatabase
from passwordsafe.unlocked_database import UnlockedDatabase


class MainWindow(Gtk.ApplicationWindow):
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-public-methods

    database_manager = NotImplemented
    container = NotImplemented
    headerbar = NotImplemented
    file_open_button = NotImplemented
    file_new_button = NotImplemented
    opened_databases: List[UnlockedDatabase] = []
    databases_to_save: List[UnlockedDatabase] = []

    mobile_layout = GObject.Property(
        type=bool, default=False, flags=GObject.ParamFlags.READWRITE)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.application = self.get_application()
        self._info_bar = None
        self._info_bar_response_id = None

        self.assemble_window()

        if Gio.Application.get_default().development_mode is True:
            passwordsafe.config_manager.set_development_backup_mode(True)

    def assemble_window(self) -> None:
        window_size = passwordsafe.config_manager.get_window_size()
        self.set_default_size(window_size[0], window_size[1])

        self.create_headerbar()
        self.load_custom_css()
        self.apply_theme()
        self.invoke_initial_screen()

    #
    # Headerbar
    #

    def create_headerbar(self):
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/main_window.ui")

        self.headerbar = builder.get_object("headerbar")

        self.file_open_button = builder.get_object("open_button")
        self.file_open_button.connect("clicked", self.open_filechooser)

        self.file_new_button = builder.get_object("new_button")
        self.file_new_button.connect("clicked", self.create_filechooser)

        self.set_headerbar_button_layout()

        self.set_titlebar(self.headerbar)

        if Gio.Application.get_default().development_mode is True:
            context = self.get_style_context()
            context.add_class("devel")

    def set_headerbar(self):
        self.set_headerbar_button_layout()
        self.set_titlebar(self.headerbar)

    def get_headerbar(self):
        return self.headerbar

    #
    # Styles
    #

    def load_custom_css(self) -> None:  # pylint: disable=R0201
        """Load passwordsafe.css and enable it"""
        screen = Gdk.Screen.get_default()

        css_provider = Gtk.CssProvider()
        css_provider_resource = Gio.File.new_for_uri(
            "resource:///org/gnome/PasswordSafe/passwordsafe.css")
        css_provider.load_from_file(css_provider_resource)

        context = Gtk.StyleContext()
        context.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def apply_theme(self) -> None:  # pylint: disable=R0201
        """Set the bright/dark theme depending on the configuration"""
        gtk_settings = Gtk.Settings.get_default()

        gtk_settings.set_property(
            "gtk-application-prefer-dark-theme",
            passwordsafe.config_manager.get_dark_theme())

    #
    # Responsive Listener
    #

    def do_size_allocate(self, allocation: Gdk.Rectangle) -> None:  # pylint: disable=W0221
        """Handler for resizing event. It is used to check if
        the layout needs to be updated.

        :param GdkEvent event: event
        """
        new_mobile_layout = (self.get_allocation().width < 700)
        if new_mobile_layout != self.props.mobile_layout:
            self.props.mobile_layout = new_mobile_layout
            self.change_layout()

        Gtk.ApplicationWindow.do_size_allocate(self, allocation)

    def change_layout(self):
        """Switches all open databases between mobile/desktop layout"""
        for db in self.opened_databases:  # pylint: disable=C0103
            # Do Nothing on Lock Screen
            if db.props.database_locked:
                return

            # Do nothing for Search View
            if db.props.search_active:
                return

            scrolled_page = db.get_current_page()

            # For Group/Entry Edit Page
            if scrolled_page.edit_page:
                return

        if self.container is NotImplemented \
           or self.container.get_n_pages() == 0:
            self.set_headerbar_button_layout()

    def set_headerbar_button_layout(self):
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/main_window.ui")

        if self.props.mobile_layout:
            self.file_open_button.get_children()[0].set_visible_child_name("mobile")
            self.file_new_button.get_children()[0].set_visible_child_name("mobile")
        else:
            self.file_open_button.get_children()[0].set_visible_child_name("desktop")
            self.file_new_button.get_children()[0].set_visible_child_name("desktop")

    #
    # First Start Screen
    #

    def invoke_initial_screen(self) -> None:
        """Present the first start screen if required or autoload files

        If the configuration is set to automatically load the last
        opened safe, this function does that. If it is not set to
        autoload, it presents a list of recently loaded files (or
        displays the empty welcome page if there are no recently
        loaded files).
        """
        if self.application.file_list:
            # file_list is appended to when we invoke the app with
            # files as cmd line parameters. (it is also appended to
            # whenever we open a file via app.open action). If it is
            # populated, simply load those files and don't show any
            # screens.
            for g_file in self.application.file_list:
                self.start_database_opening_routine(g_file.get_path())
            return

        if passwordsafe.config_manager.get_first_start_screen():
            # simply load the last opened file
            filepath = None
            file: Gio.File = Gio.File.new_for_uri(
                passwordsafe.config_manager.get_last_opened_database()
            )
            if Gio.File.query_exists(file):
                filepath = file.get_path()
                logging.debug("Opening last opened database: %s", filepath)
                self.start_database_opening_routine(filepath)
                return

        # Display the screen with last opened files (or welcome page)
        self.display_recent_files_list()

    def display_recent_files_list(self) -> None:
        """Shows the list of recently opened files or invokes welcome page"""
        builder = Gtk.Builder()
        builder.add_from_resource(
            "/org/gnome/PasswordSafe/main_window.ui")

        last_opened_list_box = builder.get_object("last_opened_list_box")
        last_opened_list_box.connect(
            "row-activated", self.on_last_opened_list_box_activated)

        entry_list = []
        pbuilder = Gtk.Builder()
        user_home: Gio.File = Gio.File.new_for_path(os.path.expanduser("~"))
        for path_uri in passwordsafe.config_manager.get_last_opened_list():
            gio_file: Gio.File = Gio.File.new_for_uri(path_uri)
            if not gio_file.query_exists():
                logging.info(
                    "Ignoring nonexistent recent file: %s", gio_file.get_path()
                )
                continue  # only work with existing files

            # Retrieve new widgets for next entry
            pbuilder.add_from_resource("/org/gnome/PasswordSafe/main_window.ui")
            last_opened_row = pbuilder.get_object("last_opened_row")
            filename_label = pbuilder.get_object("filename_label")
            path_label = pbuilder.get_object("path_label")

            # If path is not relative to user's home, use absolute path
            path: str = user_home.get_relative_path(gio_file) or gio_file.get_path()
            base_name: str = os.path.splitext(gio_file.get_basename())[0]

            filename_label.set_text(base_name)
            path_label.set_text(path)
            # last_opened_row's name will be used as file location
            last_opened_row.set_name(gio_file.get_uri())
            entry_list.append(last_opened_row)

        if not entry_list:
            self.display_welcome_page()
            return

        for row in entry_list:
            last_opened_list_box.insert(row, 0)

        first_start_grid = builder.get_object("last_opened_grid")

        # Responsive Container
        hdy = Handy.Clamp()
        hdy.set_maximum_size(400)
        hdy.props.vexpand = True
        hdy.add(builder.get_object("select_box"))

        first_start_grid.add(hdy)
        first_start_grid.show_all()

        self.add(first_start_grid)

    def display_welcome_page(self) -> None:
        """Shown when there is no autoloading and no recent files to display"""
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/main_window.ui")

        pix = Pixbuf.new_from_resource_at_scale(
            "/org/gnome/PasswordSafe/images/welcome.png", 256, 256, True)

        app_logo = builder.get_object("app_logo")
        app_logo.set_from_pixbuf(pix)
        first_start_grid = builder.get_object("first_start_grid")
        self.add(first_start_grid)

    #
    # Container Methods (Gtk Notebook holds tabs)
    #

    def create_container(self):
        # Remove the first_start_grid if still visible
        for child in self.get_children():
            if child.props.name == "first_start_grid":
                child.destroy()
                break
        self.container = Gtk.Notebook()

        self.container.set_border_width(0)
        self.container.set_scrollable(True)
        self.container.set_show_border(False)
        self.container.connect("switch-page", self.on_tab_switch)
        self.add(self.container)
        self.show_all()

    #
    # Open Database Methods
    #

    def _on_info_bar_response(self, _info_bar=None, _response_id=None):
        self._info_bar.hide()
        self._info_bar.disconnect(self._info_bar_response_id)
        self._info_bar = None
        self._info_bar_response_id = None

    def open_filechooser(self, _widget, _user_data=None):
        """Callback function to open a safe.

        This callback can be called from an action activate event or
        a clicked event from a button. In the latter case, no user_data
        is set. Having None as a default value allows to handle both
        events reliably.
        """
        # pylint: disable=too-many-locals
        if self._info_bar is not None:
            self._on_info_bar_response()

        filechooser_opening_dialog = Gtk.FileChooserNative.new(
            # NOTE: Filechooser title for opening an existing keepass safe kdbx file
            _("Choose a Keepass safe"), self, Gtk.FileChooserAction.OPEN,
            None, None)

        supported_mime_types = [
            "application/x-keepass2",
            "application/octet-stream"
        ]

        filter_text = Gtk.FileFilter()
        # NOTE: KeePass + version number is a proper name, do not translate
        filter_text.set_name(_("KeePass 3.1/4 Database"))
        for mime_type in supported_mime_types:
            filter_text.add_mime_type(mime_type)
        filechooser_opening_dialog.add_filter(filter_text)
        filechooser_opening_dialog.set_local_only(False)

        response = filechooser_opening_dialog.run()

        if response == Gtk.ResponseType.ACCEPT:
            db_filename = filechooser_opening_dialog.get_filename()
            logging.debug("File selected: %s", db_filename)

            db_gfile = Gio.File.new_for_path(db_filename)
            try:
                db_file_info = db_gfile.query_info(
                    "standard::content-type", Gio.FileQueryInfoFlags.NONE, None
                )
            except GLib.Error as e:  # pylint: disable=C0103
                logging.debug(
                    "Unable to query info for file %s: %s", db_filename, e.message
                )
                return

            file_content_type = db_file_info.get_content_type()
            file_mime_type = Gio.content_type_get_mime_type(file_content_type)
            if file_mime_type not in supported_mime_types:
                logging.debug(
                    "Unsupported mime type: %s", file_mime_type)
                main_message = _(
                    'Unable to open file "{}".'.format(db_filename))
                mime_desc = Gio.content_type_get_description(file_content_type)
                second_message = _(
                    "File type {} ({}) is not supported.".format(
                        mime_desc, file_mime_type))
                self._info_bar = ErrorInfoBar(main_message, second_message)
                self._info_bar_response_id = self._info_bar.connect(
                    "response", self._on_info_bar_response)

                # Get 1st child of  first_start_grid, to attach the info bar
                first_start_grid = None
                for child in self.get_children():
                    if child.props.name == "first_start_grid":
                        first_start_grid = child
                        break
                # FIXME: we should open the error in the info bar,
                # but there is no first_start_grid to attach it to. At
                # least don't crash now, this needs better fixing.
                if first_start_grid is None:
                    return
                first_child = self.get_children()[0]
                first_start_grid.attach_next_to(
                    self._info_bar, first_child, Gtk.PositionType.TOP, 1, 1)
                return

            database_already_opened = False

            for db in self.opened_databases:  # pylint: disable=C0103
                if db.database_manager.database_path == db_filename:
                    database_already_opened = True
                    page_num = self.container.page_num(db.parent_widget)
                    self.container.set_current_page(page_num)
                    db.show_database_action_revealer("Safe already opened")

            if database_already_opened is False:
                self.start_database_opening_routine(db_filename)
        elif response == Gtk.ResponseType.CANCEL:
            logging.debug("File selection canceled")

    def start_database_opening_routine(self, filepath: str) -> None:
        """Start opening a safe file"""
        builder = Gtk.Builder()
        builder.add_from_resource(
            "/org/gnome/PasswordSafe/create_database_headerbar.ui")
        headerbar = builder.get_object("headerbar")
        tab_title: str = os.path.basename(filepath)
        UnlockDatabase(self, self.create_tab(tab_title, headerbar), filepath)

    #
    # Create Database Methods
    #

    def create_filechooser(self, _widget, _user_data=None):
        """Callback function to create a new safe.

        This callback can be called from an action activate event or
        a clicked event from a button. In the latter case, no user_data
        is set. Having None as a default value allows to handle both
        events reliably.
        """
        filechooser_creation_dialog = Gtk.FileChooserNative.new(
            # NOTE: Filechooser title for creating a new keepass safe kdbx file
            _("Choose location for Keepass safe"),
            self,
            Gtk.FileChooserAction.SAVE,
            _("Create"),
            None,
        )
        filechooser_creation_dialog.set_do_overwrite_confirmation(True)
        filechooser_creation_dialog.set_current_name(_("Safe") + ".kdbx")
        filechooser_creation_dialog.set_modal(True)
        filechooser_creation_dialog.set_local_only(False)

        filter_text = Gtk.FileFilter()
        # NOTE: KeePass + version number is a proper name, do not translate
        filter_text.set_name(_("KeePass 3.1/4 Database"))
        filter_text.add_mime_type("application/x-keepass2")
        filechooser_creation_dialog.add_filter(filter_text)

        response = filechooser_creation_dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            filepath = filechooser_creation_dialog.get_filename()

            # Remove first_start_grid and attach the spinner
            for child in self.get_children():
                if child.props.name == "first_start_grid":
                    child.destroy()
                    break
            builder = Gtk.Builder()
            builder.add_from_resource("/org/gnome/PasswordSafe/main_window.ui")
            if self.get_children()[0] is not self.container:
                spinner = builder.get_object("spinner")
                self.add(spinner)

            creation_thread = threading.Thread(
                target=self.create_new_database, args=[filepath]
            )
            creation_thread.daemon = True
            creation_thread.start()

    def create_new_database(self, filepath: str) -> None:
        """invoked in a separate thread to create a new safe."""

        # Copy our stock database file to `filepath`
        stock_db_file: Gio.File = Gio.File.new_for_uri(
            "resource:///org/gnome/PasswordSafe/database.kdbx")
        new_db_file: Gio.File = Gio.File.new_for_path(filepath)
        stock_db_file.copy(new_db_file, Gio.FileCopyFlags.OVERWRITE)

        tab_title: str = os.path.basename(filepath)
        self.database_manager = DatabaseManager(filepath,
                                                "liufhre86ewoiwejmrcu8owe")
        GLib.idle_add(self.start_database_creation_routine, tab_title)

    def start_database_creation_routine(self, tab_title):
        for child in self.get_children():
            if child.props.name == "spinner":
                child.destroy()
                break

        builder = Gtk.Builder()
        builder.add_from_resource(
            "/org/gnome/PasswordSafe/create_database_headerbar.ui")
        headerbar = builder.get_object("headerbar")
        parent_widget = self.create_tab(tab_title, headerbar)
        create_database = CreateDatabase(
            self, parent_widget,
            self.database_manager)
        parent_widget.add(create_database)

    #
    # Tab Manager
    #

    def create_tab(self, title, headerbar):
        if self.container == NotImplemented:
            self.create_container()

        page_instance = ContainerPage(headerbar, Gio.Application.get_default().development_mode)

        tab_hbox = Gtk.Box.new(False, 0)
        tab_label = Gtk.Label.new(title)
        tab_hbox.pack_start(tab_label, False, False, False)

        icon = Gio.ThemedIcon(name="window-close-symbolic")
        close_image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        close_button = Gtk.Button()
        close_button.set_relief(Gtk.ReliefStyle.NONE)
        close_button.set_focus_on_click(False)
        close_button.connect("clicked", self.on_tab_close_button_clicked, page_instance)
        close_button.add(close_image)

        tab_hbox.pack_start(close_button, False, False, False)
        tab_hbox.show_all()

        self.container.append_page(page_instance, tab_hbox)
        self.container.set_current_page(self.container.page_num(page_instance))
        self.update_tab_bar_visibility()

        return page_instance

    def update_tab_bar_visibility(self):
        if self.container.get_n_pages() > 1:
            self.container.set_show_tabs(True)
        else:
            self.container.set_show_tabs(False)

        if not self.container.get_n_pages():
            self.container.hide()
            self.remove(self.container)
            self.display_recent_files_list()
        elif not self.container.is_visible():
            for child in self.get_children():
                if child.props.name == "first_start_grid":
                    child.destroy()
                    break
            self.add(self.container)
            self.container.show_all()

    def close_tab(self, child_widget, database=None):
        """Remove a tab from the container.

        If database is defined, it is removed from the list of
        opened_databases

        :param GtkWidget child_widget: tab to close
        :param UnlockedDatabase database: database to remove
        """
        page_num = self.container.page_num(child_widget)
        self.container.remove_page(page_num)
        self.update_tab_bar_visibility()

        if database:
            self.opened_databases.remove(database)

    #
    # Events
    #

    def on_last_opened_list_box_activated(
        self, _widget: Gtk.ListBox, list_box_row: Gtk.ListBoxRow
    ) -> None:
        """cb when we click on an entry in the recently opened files list

        Starts opening the database corresponding to the entry."""
        file_uri: str = list_box_row.get_name()
        self.start_database_opening_routine(Gio.File.new_for_uri(file_uri).get_path())

    def on_tab_close_button_clicked(self, _sender, widget):
        page_num = self.container.page_num(widget)
        current_db: Optional[UnlockedDatabase] = None

        for db in self.opened_databases:  # pylint: disable=C0103
            if db.window.container.page_num(db.parent_widget) == page_num:
                if db.database_manager.is_dirty:
                    saved: bool = db.save_database(
                        passwordsafe.config_manager.get_save_automatically())
                    # operation has been canceled
                    if not saved:
                        return

                db.cleanup()
                current_db = db
                break

        if not current_db:
            logging.warning(
                "Closing a tab, but could not find the corresponding database.")

        self.close_tab(widget, current_db)

    def on_tab_switch(self, _notebook, tab, _pagenum):
        headerbar = tab.get_headerbar()
        self.set_titlebar(headerbar)

    def on_save_check_button_toggled(self, check_button, db):  # pylint: disable=C0103
        if check_button.get_active():
            self.databases_to_save.append(db)
        else:
            self.databases_to_save.remove(db)

    #
    # Application Quit Dialog
    #

    def save_window_size(self):
        window_size = [self.get_size().width, self.get_size().height]
        passwordsafe.config_manager.set_window_size(window_size)

    def do_delete_event(self, _event: Gdk.EventAny) -> bool:  # pylint:disable=W0221
        """invoked when we hit the window close button"""
        # Just invoke the app.quit action, it cleans up stuff
        # and will invoke the on_application_shutdown()
        self.application.activate_action("quit")
        return True  # we handled event, don't call destroy

    def on_application_shutdown(self) -> bool:
        """Clean up unsaved databases, and shutdown

        This function is invoked by the application.quit method
        :returns: True if handled (don't quit), False if shutdown
        """
        # pylint: disable=too-many-branches
        unsaved_databases_list = []
        self.databases_to_save.clear()

        for db_view in self.opened_databases:
            if (db_view.database_manager.is_dirty
                    and not db_view.database_manager.save_running):
                if passwordsafe.config_manager.get_save_automatically():
                    db_view.save_database(True)
                else:
                    unsaved_databases_list.append(db_view)

        if len(unsaved_databases_list) == 1:
            database = unsaved_databases_list[0]
            saved: bool = database.save_database()
            if not saved:
                return True  # User Canceled, don't quit

        elif len(unsaved_databases_list) > 1:
            # Multiple unsaved files, ask which to save
            builder = Gtk.Builder()
            builder.add_from_resource(
                "/org/gnome/PasswordSafe/quit_dialog.ui")
            quit_dialog = builder.get_object("quit_dialog")
            quit_dialog.set_transient_for(self)

            unsaved_databases_list_box = builder.get_object("unsaved_databases_list_box")

            for db in unsaved_databases_list:  # pylint: disable=C0103
                unsaved_database_row = Gtk.ListBoxRow()
                check_button = Gtk.CheckButton()
                if "/home/" in db.database_manager.database_path:
                    check_button.set_label("~/" + os.path.relpath(db.database_manager.database_path))
                else:
                    check_button.set_label(Gio.File.new_for_path(db.database_manager.database_path).get_uri())
                check_button.connect("toggled", self.on_save_check_button_toggled, db)
                check_button.set_active(True)
                unsaved_database_row.add(check_button)
                unsaved_database_row.show_all()
                unsaved_databases_list_box.add(unsaved_database_row)

            res = quit_dialog.run()
            quit_dialog.destroy()
            if res == Gtk.ResponseType.CANCEL:
                self.databases_to_save.clear()
                return True
            # Do nothing in other cases e.g.NONE, OK,...

        for database in self.opened_databases:
            database.cleanup()

        self.save_window_size()
        if self.databases_to_save:
            for db_view in self.databases_to_save:
                db_view.save_database(True)

            GLib.idle_add(self.application.quit)

            return True

        return False  # caller should quit() the app
    #
    # Gio Actions
    #

    # Find current displayed tab for executing the action
    def find_action_db(self):
        action_db = NotImplemented

        for db in self.opened_databases:  # pylint: disable=C0103
            if self.tab_visible(db.parent_widget):
                action_db = db

        return action_db

    # Entry/Group Row Popover Actions
    def add_row_popover_actions(self):
        actions = [
            ("element.delete", "on_element_delete_menu_button_clicked"),
            ("entry.duplicate", "on_entry_duplicate_menu_button_clicked"),
            ("entry.references", "on_entry_references_menu_button_clicked"),
            ("element.properties", "on_element_properties_menu_button_clicked"),
            ("group.edit", "on_group_edit_menu_button_clicked"),
            ("group.delete", "on_group_delete_menu_button_clicked")
        ]

        for action, name in actions:
            simple_action = Gio.SimpleAction.new(action, None)
            simple_action.connect("activate", self.execute_gio_action, name)
            self.application.add_action(simple_action)

    # MenuButton Popover Actions
    def add_database_menubutton_popover_actions(self):
        actions = [
            ("db.add_entry", "on_database_add_entry_clicked", None),
            ("db.add_group", "on_database_add_group_clicked", None),
            ("db.settings", "on_database_settings_entry_clicked", None),
            ("sort.az", "on_sort_menu_button_entry_clicked", "A-Z"),
            ("sort.za", "on_sort_menu_button_entry_clicked", "Z-A"),
            ("sort.last_added", "on_sort_menu_button_entry_clicked", "last_added"),
        ]

        for action, name, arg in actions:
            simple_action = Gio.SimpleAction.new(action, None)
            simple_action.connect(
                "activate", self.execute_gio_action, name, arg)
            self.application.add_action(simple_action)

    # Selection Mode Actions
    def add_selection_actions(self):
        selection_all_action = Gio.SimpleAction.new("selection.all", None)
        selection_all_action.connect("activate", self.execute_gio_action, "on_selection_popover_button_clicked", "all")
        self.application.add_action(selection_all_action)

        selection_none_action = Gio.SimpleAction.new("selection.none", None)
        selection_none_action.connect("activate", self.execute_gio_action, "on_selection_popover_button_clicked", "none")
        self.application.add_action(selection_none_action)

    # Gio Action Handler
    def execute_gio_action(self, action, param, name, arg=None):
        action_db = self.find_action_db()
        if action_db is NotImplemented:
            return

        if name == "on_element_delete_menu_button_clicked":
            action_db.on_element_delete_menu_button_clicked(action, param)
        elif name == "on_entry_duplicate_menu_button_clicked":
            action_db.on_entry_duplicate_menu_button_clicked(action, param)
        elif name == "on_entry_references_menu_button_clicked":
            action_db.show_references_dialog(action, param)
        elif name == "on_element_properties_menu_button_clicked":
            action_db.show_properties_dialog(action, param)
        elif name == "on_group_edit_menu_button_clicked":
            action_db.on_group_edit_menu_button_clicked(action, param)
        elif name == "on_group_delete_menu_button_clicked":
            action_db.on_group_delete_menu_button_clicked(action, param)
        elif name == "on_database_add_entry_clicked":
            action_db.on_add_entry_button_clicked(None)
        elif name == "on_database_add_group_clicked":
            action_db.on_add_group_button_clicked(None)
        elif name == "on_database_settings_entry_clicked":
            action_db.on_database_settings_entry_clicked(action, param)
        elif name == "on_sort_menu_button_entry_clicked":
            action_db.on_sort_menu_button_entry_clicked(action, param, arg)
        elif name == "on_selection_popover_button_clicked":
            action_db.selection_ui.on_selection_popover_button_clicked(action, param, arg)

    # Add Global Accelerator Actions
    def add_global_accelerator_actions(self):
        actions = [
            ("db.save", "save", None),
            ("db.lock", "lock", None),
            ("db.add_entry", "add_action", "entry"),
            ("db.add_group", "add_action", "group"),
            ("go_back", "go_back", None),
        ]

        for action, name, arg in actions:
            simple_action = Gio.SimpleAction.new(action, None)
            simple_action.connect(
                "activate", self.execute_accel_action, name, arg)
            self.application.add_action(simple_action)

    # Accelerator Action Handler
    def execute_accel_action(self, _action, _param, name, arg=None):
        action_db = self.find_action_db()
        if action_db is NotImplemented:
            return

        if name == "save":
            action_db.save_safe()
        elif name == "lock":
            action_db.lock_safe()
        elif name == "go_back":
            action_db.go_back()
        elif name == "add_action":
            if action_db.props.database_locked:
                return

            if action_db.props.selection_mode:
                return

            scrolled_page = action_db.get_current_page()
            if scrolled_page.edit_page:
                return

            if action_db.props.search_active:
                return

            if arg == "entry":
                action_db.on_add_entry_button_clicked(None)
            elif arg == "group":
                action_db.on_add_group_button_clicked(None)

    #
    # Tools
    #
    def tab_visible(self, tab):
        """Checks that the tab is visible

        :returns: True if the tab is visible
        :rtype: bool
        """
        current_page = self.container.get_current_page()
        return self.container.page_num(tab) == current_page
