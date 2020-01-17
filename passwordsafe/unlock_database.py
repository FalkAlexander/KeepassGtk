from gi.repository import Gio, Gtk, GLib, Handy, Pango
from passwordsafe.database_manager import DatabaseManager
from passwordsafe.unlocked_database import UnlockedDatabase
from pykeepass.exceptions import CredentialsIntegrityError
import passwordsafe.config_manager
import ntpath
import os
import threading
import time
import datetime
from gettext import gettext as _
from construct import core
from pathlib import Path


class UnlockDatabase:
    builder = NotImplemented
    parent_widget = NotImplemented
    window = NotImplemented
    database_filepath = NotImplemented
    database_manager = NotImplemented
    hdy_page = NotImplemented
    unlock_database_stack_switcher = NotImplemented
    keyfile_path = NotImplemented
    composite_keyfile_path = NotImplemented
    overlay = NotImplemented
    timeout = NotImplemented
    unlocked_database = NotImplemented
    original_group = NotImplemented
    original_group_edit_page = NotImplemented
    password_only = NotImplemented
    unlock_thread = NotImplemented

    def __init__(self, window, widget, filepath):
        self.window = window
        self.parent_widget = widget
        self.database_filepath = filepath
        self.unlock_database()

    def unlock_database(self, timeout=None, unlocked_database=None, original_group=NotImplemented, original_group_edit_page=False):
        self.timeout = timeout
        self.unlocked_database = unlocked_database
        self.original_group = original_group
        self.original_group_edit_page = original_group_edit_page

        self.builder = Gtk.Builder()
        self.builder.add_from_resource("/org/gnome/PasswordSafe/unlock_database.ui")

        self.set_headerbar()
        self.assemble_stack()

    #
    # Headerbar
    #

    def set_headerbar(self):
        headerbar = self.builder.get_object("headerbar")

        if "/home/" in self.database_filepath:
            headerbar.set_subtitle("~/" + os.path.relpath(self.database_filepath))
        else:
            headerbar.set_subtitle(Gio.File.new_for_path(self.database_filepath).get_uri())

        if self.timeout is True and self.window.container.get_current_page() == self.window.container.page_num(self.parent_widget):
            self.window.set_titlebar(headerbar)
        elif self.timeout is not True:
            self.window.set_titlebar(headerbar)

        self.parent_widget.set_headerbar(headerbar)
        back_button = self.builder.get_object("back_button")
        back_button.connect("clicked", self.on_headerbar_back_button_clicked)

    #
    # Password stack
    #

    def assemble_stack(self):
        self.overlay = Gtk.Overlay()

        unlock_failed_overlay = self.builder.get_object("unlock_failed_overlay")
        self.overlay.add_overlay(unlock_failed_overlay)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        unlock_database_stack_box = self.builder.get_object("unlock_database_stack_box")
        self.unlock_database_stack_switcher = self.builder.get_object("unlock_database_stack_switcher")
        self.unlock_database_stack_switcher.set_stack(stack)

        password_unlock_stack_page = self.builder.get_object("password_unlock_stack_page")
        keyfile_unlock_stack_page = self.builder.get_object("keyfile_unlock_stack_page")
        composite_unlock_stack_page = self.builder.get_object("composite_unlock_stack_page")

        stack.add_titled(password_unlock_stack_page, "password_unlock", _("Password"))
        stack.child_set_property(password_unlock_stack_page, "icon-name", "input-dialpad-symbolic")

        stack.add_titled(keyfile_unlock_stack_page, "keyfile_unlock", _("Keyfile"))
        stack.child_set_property(keyfile_unlock_stack_page, "icon-name", "mail-attachment-symbolic")

        # NOTE: Composite unlock is a authentification method where both password and keyfile are required
        stack.add_titled(composite_unlock_stack_page, "composite_unlock", _("Composite"))
        stack.child_set_property(composite_unlock_stack_page, "icon-name", "insert-link-symbolic")

        pairs = passwordsafe.config_manager.get_last_used_composite_key()
        uri = Gio.File.new_for_path(self.database_filepath).get_uri()
        if passwordsafe.config_manager.get_remember_composite_key() is True and pairs:
            keyfile_path = None

            for pair in pairs:
                if pair[0] == uri:
                    keyfile_path = pair[1]

            if keyfile_path is not None:
                composite_unlock_select_button = self.builder.get_object("composite_unlock_select_button")
                label = Gtk.Label()
                label.set_text(ntpath.basename(keyfile_path))
                label.set_ellipsize(Pango.EllipsizeMode.END)
                composite_unlock_select_button.remove(composite_unlock_select_button.get_children()[0])
                composite_unlock_select_button.add(label)

                self.composite_keyfile_path = keyfile_path

        if passwordsafe.config_manager.get_remember_unlock_method() is True:
            stack.set_visible_child(stack.get_child_by_name(passwordsafe.config_manager.get_unlock_method() + "_unlock"))

        self.overlay.add(stack)
        unlock_database_stack_box.add(self.overlay)
        unlock_database_stack_box.show_all()

        # Responsive Container
        self.hdy_page = Handy.Column()
        self.hdy_page.set_maximum_width(300)
        self.hdy_page.set_margin_left(15)
        self.hdy_page.set_margin_right(15)
        self.hdy_page.add(unlock_database_stack_box)
        self.hdy_page.show_all()

        self.parent_widget.add(self.hdy_page)

        self.connect_events(stack)

    def connect_events(self, stack):
        password_unlock_button = self.builder.get_object("password_unlock_button")
        password_unlock_button.connect("clicked", self.on_password_unlock_button_clicked)

        keyfile_unlock_button = self.builder.get_object("keyfile_unlock_button")
        keyfile_unlock_button.connect("clicked", self.on_keyfile_unlock_button_clicked)

        composite_unlock_button = self.builder.get_object("composite_unlock_button")
        composite_unlock_button.connect("clicked", self.on_composite_unlock_button_clicked)

        keyfile_unlock_select_button = self.builder.get_object("keyfile_unlock_select_button")
        keyfile_unlock_select_button.connect("clicked", self.on_keyfile_unlock_select_button_clicked)

        composite_unlock_select_button = self.builder.get_object("composite_unlock_select_button")
        composite_unlock_select_button.connect("clicked", self.on_composite_unlock_select_button_clicked)

        password_unlock_entry = self.builder.get_object("password_unlock_entry")
        if stack.get_visible_child_name() == "password_unlock":
            password_unlock_entry.grab_focus()
        password_unlock_entry.connect("activate", self.on_password_unlock_button_clicked)
        password_unlock_entry.connect("icon-press", self.on_password_unlock_entry_secondary_clicked)

        composite_unlock_entry = self.builder.get_object("composite_unlock_entry")
        composite_unlock_entry.connect("activate", self.on_composite_unlock_button_clicked)
        if stack.get_visible_child_name() == "composite_unlock":
            composite_unlock_entry.grab_focus()

    #
    # Events
    #

    def on_headerbar_back_button_clicked(self, widget):
        if self.timeout is True:
            for db in self.window.opened_databases:
                if db.database_manager.database_path == self.database_manager.database_path:
                    db.unregister_dbus_signal()
                    db.cancel_timers()

                    if passwordsafe.config_manager.get_save_automatically() is True:
                        save_thread = threading.Thread(target=db.database_manager.save_database)
                        save_thread.daemon = False
                        save_thread.start()

                    db.stop_save_loop()
                    self.window.opened_databases.remove(db)
        self.window.set_headerbar()
        self.window.close_tab(self.parent_widget)

    # Password Unlock

    def on_password_unlock_entry_secondary_clicked(self, widget, position, eventbutton):
        if widget.get_visibility():
            widget.set_invisible_char("●")
            widget.set_visibility(False)
        else:
            widget.set_visibility(True)

    def on_password_unlock_button_clicked(self, widget):
        password_unlock_entry = self.builder.get_object("password_unlock_entry")

        database_already_opened = False

        for db in self.window.opened_databases:
            if db.database_manager.database_path == self.database_filepath and self.timeout is not True:
                database_already_opened = True
                page_num = self.window.container.page_num(db.parent_widget)
                self.window.container.set_current_page(page_num)

                current_page_num = self.window.container.page_num(self.parent_widget)
                self.window.container.remove_page(current_page_num)
                self.window.update_tab_bar_visibility()

                db.show_database_action_revealer(_("Database already opened"))

        if password_unlock_entry.get_text() != "" and database_already_opened is False:
            if self.timeout is True:
                if password_unlock_entry.get_text() == self.unlocked_database.database_manager.password and self.unlocked_database.database_manager.keyfile_hash is NotImplemented:
                    self.parent_widget.remove(self.hdy_page)
                    if self.unlocked_database.search.search_active is True:
                        self.parent_widget.set_headerbar(self.unlocked_database.headerbar_search)
                        self.window.set_titlebar(self.unlocked_database.headerbar_search)
                    else:
                        self.parent_widget.set_headerbar(self.unlocked_database.headerbar)
                        self.window.set_titlebar(self.unlocked_database.headerbar)

                    self.unlocked_database.start_save_loop()
                    self.unlocked_database.overlay.show()
                    self.unlocked_database.database_locked = False
                    if self.original_group is not NotImplemented:
                        self.unlocked_database.current_group = self.original_group
                        if self.original_group_edit_page is True:
                            self.unlocked_database.show_page_of_new_directory(True, False)
                        else:
                            self.unlocked_database.show_page_of_new_directory(False, False)

                    self.unlocked_database.start_database_lock_timer()
                else:
                    self.show_unlock_failed_revealer()
                    password_unlock_entry.grab_focus()
                    password_unlock_entry.get_style_context().add_class("error")
                    self.clear_input_fields()
                    self.window.logging_manager.debug("Could not open database, wrong password")
            else:
                password_unlock_button = self.builder.get_object("password_unlock_button")
                password_unlock_button_image = password_unlock_button.get_children()[0]
                password_unlock_entry.set_sensitive(False)
                password_unlock_button.set_sensitive(False)
                self.unlock_database_stack_switcher.set_sensitive(False)

                spinner = Gtk.Spinner()
                spinner.show()
                spinner.start()

                password_unlock_button.remove(password_unlock_button_image)
                password_unlock_button.add(spinner)

                self.password_only = password_unlock_entry.get_text()
                self.unlock_thread = threading.Thread(target=self.password_unlock_process)
                self.unlock_thread.daemon = True
                self.unlock_thread.start()

    def password_unlock_process(self):
        try:
            self.database_manager = DatabaseManager(self.database_filepath, password=self.password_only, keyfile=None, logging_manager=self.window.logging_manager)
            GLib.idle_add(self.password_unlock_success)
        except(OSError, ValueError, AttributeError, core.ChecksumError, CredentialsIntegrityError):
            GLib.idle_add(self.password_unlock_failure)

    def password_unlock_success(self):
        if Path(self.database_filepath).suffix == ".kdb":
            self.password_unlock_failure()
            return

        self.password_only = NotImplemented
        self.set_last_used_unlock_method("password")
        self.window.logging_manager.debug("Opening of database was successfull")
        self.open_database_page()

    def password_unlock_failure(self):
        password_unlock_button = self.builder.get_object("password_unlock_button")
        password_unlock_button.remove(password_unlock_button.get_children()[0])
        password_unlock_button.add(self.builder.get_object("password_unlock_button_image"))
        password_unlock_entry = self.builder.get_object("password_unlock_entry")
        password_unlock_entry.set_sensitive(True)
        self.unlock_database_stack_switcher.set_sensitive(True)
        password_unlock_button.set_sensitive(True)

        self.show_unlock_failed_revealer()

        password_unlock_entry.grab_focus()
        password_unlock_entry.get_style_context().add_class("error")
        self.clear_input_fields()
        self.window.logging_manager.debug("Could not open database, wrong password")

    # Keyfile Unlock

    def on_keyfile_unlock_select_button_clicked(self, widget):
        # NOTE: Keyfile filechooser title
        keyfile_chooser_dialog = Gtk.FileChooserNative.new(_("Choose a keyfile"), self.window, Gtk.FileChooserAction.OPEN, None, None)
        filter_text = Gtk.FileFilter()
        filter_text.set_name(_("Keyfile"))
        filter_text.add_mime_type("application/octet-stream")
        filter_text.add_mime_type("application/x-keepass2")
        filter_text.add_mime_type("text/plain")
        filter_text.add_mime_type("application/x-iwork-keynote-sffkey")
        keyfile_chooser_dialog.add_filter(filter_text)
        keyfile_chooser_dialog.set_local_only(False)

        response = keyfile_chooser_dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            self.window.logging_manager.debug("File selected: " + keyfile_chooser_dialog.get_filename())

            keyfile_unlock_select_button = self.builder.get_object("keyfile_unlock_select_button")
            keyfile_unlock_select_button.get_style_context().remove_class(Gtk.STYLE_CLASS_DESTRUCTIVE_ACTION)
            keyfile_unlock_select_button.get_style_context().add_class(Gtk.STYLE_CLASS_SUGGESTED_ACTION)
            keyfile_unlock_select_button.set_label(ntpath.basename(keyfile_chooser_dialog.get_filename()))

            self.keyfile_path = keyfile_chooser_dialog.get_filename()

        elif response == Gtk.ResponseType.CANCEL:
            self.window.logging_manager.debug("File selection canceled")

    def on_keyfile_unlock_button_clicked(self, widget):
        keyfile_unlock_select_button = self.builder.get_object("keyfile_unlock_select_button")

        if self.timeout is True:
            if self.keyfile_path is not NotImplemented and self.unlocked_database.database_manager.keyfile_hash == self.database_manager.create_keyfile_hash(self.keyfile_path):
                self.parent_widget.remove(self.hdy_page)
                self.keyfile_path = NotImplemented
                if self.unlocked_database.search.search_active is True:
                    self.parent_widget.set_headerbar(self.unlocked_database.headerbar_search)
                    self.window.set_titlebar(self.unlocked_database.headerbar_search)
                else:
                    self.parent_widget.set_headerbar(self.unlocked_database.headerbar)
                    self.window.set_titlebar(self.unlocked_database.headerbar)

                self.unlocked_database.start_save_loop()
                self.unlocked_database.overlay.show()
                self.unlocked_database.database_locked = False
                if self.original_group is not NotImplemented:
                    self.unlocked_database.current_group = self.original_group
                    if self.original_group_edit_page is True:
                        self.unlocked_database.show_page_of_new_directory(True, False)
                    else:
                        self.unlocked_database.show_page_of_new_directory(False, False)

                self.unlocked_database.start_database_lock_timer()
            else:
                self.show_unlock_failed_revealer()

                keyfile_unlock_select_button.get_style_context().add_class(Gtk.STYLE_CLASS_DESTRUCTIVE_ACTION)
                keyfile_unlock_select_button.set_label(_("Try again"))

                self.window.logging_manager.debug("Invalid keyfile chosen")
        elif self.keyfile_path is not NotImplemented:
            keyfile_unlock_select_button = self.builder.get_object("keyfile_unlock_select_button")
            keyfile_unlock_button = self.builder.get_object("keyfile_unlock_button")
            keyfile_unlock_button_image = keyfile_unlock_button.get_children()[0]
            keyfile_unlock_select_button.set_sensitive(False)
            keyfile_unlock_button.set_sensitive(False)
            self.unlock_database_stack_switcher.set_sensitive(False)

            spinner = Gtk.Spinner()
            spinner.show()
            spinner.start()

            keyfile_unlock_button.remove(keyfile_unlock_button_image)
            keyfile_unlock_button.add(spinner)

            self.unlock_thread = threading.Thread(target=self.keyfile_unlock_process)
            self.unlock_thread.daemon = True
            self.unlock_thread.start()

    def keyfile_unlock_process(self):
        try:
            self.database_manager = DatabaseManager(self.database_filepath, password=None, keyfile=self.keyfile_path, logging_manager=self.window.logging_manager)
            GLib.idle_add(self.keyfile_unlock_success)
        except(OSError, IndexError, ValueError, AttributeError, core.ChecksumError, CredentialsIntegrityError):
            GLib.idle_add(self.keyfile_unlock_failure)

    def keyfile_unlock_success(self):
        self.database_manager.set_keyfile_hash(self.keyfile_path)

        if Path(self.database_filepath).suffix == ".kdb":
            self.keyfile_unlock_failure()
            return

        self.set_last_used_unlock_method("keyfile")
        self.window.logging_manager.debug("Database successfully opened with keyfile")
        self.keyfile_path = NotImplemented
        self.open_database_page()

    def keyfile_unlock_failure(self):
        keyfile_unlock_select_button = self.builder.get_object("keyfile_unlock_select_button")
        keyfile_unlock_button = self.builder.get_object("keyfile_unlock_button")
        keyfile_unlock_button.remove(keyfile_unlock_button.get_children()[0])
        keyfile_unlock_button.add(self.builder.get_object("keyfile_unlock_button_image"))
        keyfile_unlock_select_button = self.builder.get_object("keyfile_unlock_select_button")
        keyfile_unlock_select_button.set_sensitive(True)
        keyfile_unlock_button.set_sensitive(True)
        self.unlock_database_stack_switcher.set_sensitive(True)

        self.show_unlock_failed_revealer()

        if self.database_manager is not NotImplemented:
                self.database_manager.keyfile_hash = NotImplemented

        keyfile_unlock_select_button.get_style_context().add_class(Gtk.STYLE_CLASS_DESTRUCTIVE_ACTION)
        keyfile_unlock_select_button.set_label(_("Try again"))

        self.window.logging_manager.debug("Invalid keyfile chosen")

    # Composite Unlock

    def on_composite_unlock_select_button_clicked(self, widget):
        filechooser_opening_dialog = Gtk.FileChooserNative.new(
            # NOTE: Keyfile filechooser title
            _("Choose Keyfile"), self.window, Gtk.FileChooserAction.OPEN,
            None, None)
        composite_unlock_select_button = self.builder.get_object("composite_unlock_select_button")

        filter_text = Gtk.FileFilter()
        filter_text.set_name(_("Keyfile"))
        filter_text.add_mime_type("application/octet-stream")
        filter_text.add_mime_type("application/x-keepass2")
        filter_text.add_mime_type("text/plain")
        filter_text.add_mime_type("application/x-iwork-keynote-sffkey")
        filechooser_opening_dialog.add_filter(filter_text)
        filechooser_opening_dialog.set_local_only(False)

        response = filechooser_opening_dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            self.window.logging_manager.debug("File selected: " + filechooser_opening_dialog.get_filename())
            file_path = filechooser_opening_dialog.get_filename()

            label = Gtk.Label()
            label.set_text(ntpath.basename(file_path))
            label.set_ellipsize(Pango.EllipsizeMode.END)
            composite_unlock_select_button.remove(composite_unlock_select_button.get_children()[0])
            composite_unlock_select_button.add(label)
            composite_unlock_select_button.show_all()

            self.composite_keyfile_path = file_path
        elif response == Gtk.ResponseType.CANCEL:
            self.window.logging_manager.debug("File selection cancelled")

    def on_composite_unlock_button_clicked(self, widget):
        composite_unlock_entry = self.builder.get_object("composite_unlock_entry")
        composite_unlock_select_button = self.builder.get_object("composite_unlock_select_button")

        if self.timeout is True:
            if (self.composite_keyfile_path is not NotImplemented) and (self.unlocked_database.database_manager.keyfile_hash == self.database_manager.create_keyfile_hash(self.composite_keyfile_path)) and (composite_unlock_entry.get_text() == self.unlocked_database.database_manager.password):
                self.parent_widget.remove(self.hdy_page)
                if self.unlocked_database.search.search_active is True:
                    self.parent_widget.set_headerbar(self.unlocked_database.headerbar_search)
                    self.window.set_titlebar(self.unlocked_database.headerbar_search)
                else:
                    self.parent_widget.set_headerbar(self.unlocked_database.headerbar)
                    self.window.set_titlebar(self.unlocked_database.headerbar)

                self.unlocked_database.start_save_loop()
                self.unlocked_database.overlay.show()
                self.unlocked_database.database_locked = False
                if self.original_group is not NotImplemented:
                    self.unlocked_database.current_group = self.original_group
                    if self.original_group_edit_page is True:
                        self.unlocked_database.show_page_of_new_directory(True, False)
                    else:
                        self.unlocked_database.show_page_of_new_directory(False, False)

                self.unlocked_database.start_database_lock_timer()
            else:
                self.show_unlock_failed_revealer()

                composite_unlock_entry.grab_focus()
                composite_unlock_entry.get_style_context().add_class("error")
                composite_unlock_select_button.get_style_context().remove_class("suggested-action")
                composite_unlock_select_button.get_style_context().add_class("destructive-action")
                self.clear_input_fields()

                self.window.logging_manager.debug("Could not open database, wrong password")
        else:
            if composite_unlock_entry.get_text() is not "" and self.composite_keyfile_path is not NotImplemented:
                composite_unlock_select_button = self.builder.get_object("composite_unlock_select_button")
                composite_unlock_button = self.builder.get_object("composite_unlock_button")
                composite_unlock_button_image = composite_unlock_button.get_children()[0]
                composite_unlock_select_button.set_sensitive(False)
                composite_unlock_button.set_sensitive(False)
                composite_unlock_entry.set_sensitive(False)
                self.unlock_database_stack_switcher.set_sensitive(False)

                spinner = Gtk.Spinner()
                spinner.show()
                spinner.start()

                composite_unlock_button.remove(composite_unlock_button_image)
                composite_unlock_button.add(spinner)

                self.password_composite = composite_unlock_entry.get_text()
                self.unlock_thread = threading.Thread(target=self.composite_unlock_process)
                self.unlock_thread.daemon = True
                self.unlock_thread.start()
            else:
                composite_unlock_entry.get_style_context().add_class("error")

    def composite_unlock_process(self):
        try:
            self.database_manager = DatabaseManager(self.database_filepath, password=self.password_composite, keyfile=self.composite_keyfile_path, logging_manager=self.window.logging_manager)
            GLib.idle_add(self.composite_unlock_success)
        except(OSError, IndexError, ValueError, AttributeError, core.ChecksumError, CredentialsIntegrityError):
            GLib.idle_add(self.composite_unlock_failure)

    def composite_unlock_success(self):
        self.password_composite = NotImplemented
        self.database_manager.set_keyfile_hash(self.composite_keyfile_path)

        if Path(self.database_filepath).suffix == ".kdb":
            self.composite_unlock_failure()
            return

        pairs = passwordsafe.config_manager.get_last_used_composite_key()
        uri = Gio.File.new_for_path(self.database_filepath).get_uri()
        if passwordsafe.config_manager.get_remember_composite_key() is True and self.composite_keyfile_path is not NotImplemented:
            pair_array = []
            already_added = False

            for pair in pairs:
                pair_array.append([pair[0], pair[1]])

            for pair in pair_array:
                if pair[0] == uri:
                    pair[1] = self.composite_keyfile_path
                    already_added = True

            if already_added is False:
                pair_array.append([uri, self.composite_keyfile_path])
            passwordsafe.config_manager.set_last_used_composite_key(pair_array)

        self.set_last_used_unlock_method("composite")
        self.window.logging_manager.debug("Opening of database was successfull")
        self.composite_keyfile_path = NotImplemented
        self.open_database_page()

    def composite_unlock_failure(self):
        composite_unlock_select_button = self.builder.get_object("composite_unlock_select_button")
        composite_unlock_button = self.builder.get_object("composite_unlock_button")
        composite_unlock_button.remove(composite_unlock_button.get_children()[0])
        composite_unlock_button.add(self.builder.get_object("composite_unlock_button_image"))
        composite_unlock_select_button.set_sensitive(True)
        composite_unlock_button.set_sensitive(True)
        composite_unlock_entry = self.builder.get_object("composite_unlock_entry")
        composite_unlock_entry.set_sensitive(True)
        self.unlock_database_stack_switcher.set_sensitive(True)

        self.show_unlock_failed_revealer()

        if self.database_manager is not NotImplemented:
            self.database_manager.keyfile_hash = NotImplemented

        composite_unlock_entry.grab_focus()
        composite_unlock_entry.get_style_context().add_class("error")
        composite_unlock_select_button.get_style_context().remove_class("suggested-action")
        composite_unlock_select_button.get_style_context().add_class("destructive-action")
        self.clear_input_fields()

        self.window.logging_manager.debug("Could not open database, wrong password")

    #
    # Open Database
    #

    def open_database_page(self):
        self.clear_input_fields()
        passwordsafe.config_manager.set_last_opened_database(Gio.File.new_for_path(self.database_filepath).get_uri())

        if passwordsafe.config_manager.get_development_backup_mode() is True:
            cache_dir = os.path.expanduser("~") + "/.cache/passwordsafe/backup"
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)

            opened = Gio.File.new_for_path(self.database_filepath)
            backup = Gio.File.new_for_path(cache_dir + "/" + os.path.splitext(ntpath.basename(self.database_filepath))[0] + "_backup_" + datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%H:%M:%S') + ".kdbx")
            try:
                opened.copy(backup, Gio.FileCopyFlags.NONE)
            except GLib.Error:
                self.window.logging_manager.warning("Could not copy database file to backup location. This most likely happened because the database is located on a network drive, and Password Safe doesn't have network permission. Either disable development-backup-mode or if PasswordSafe runs as Flatpak grant network permission")

        already_added = False
        list = []
        for path in passwordsafe.config_manager.get_last_opened_list():
            list.append(path)
            if path == Gio.File.new_for_path(self.database_filepath).get_uri():
                already_added = True

        if already_added is False:
            list.append(Gio.File.new_for_path(self.database_filepath).get_uri())
        else:
            list.sort(key=Gio.File.new_for_path(self.database_filepath).get_uri().__eq__)

        if len(list) > 10:
            list.pop(0)

        passwordsafe.config_manager.set_last_opened_list(list)

        self.hdy_page.destroy()
        UnlockedDatabase(self.window, self.parent_widget, self.database_manager, self)

    #
    # Helper Functions
    #

    def clear_input_fields(self):
        password_unlock_entry = self.builder.get_object("password_unlock_entry")
        composite_unlock_entry = self.builder.get_object("composite_unlock_entry")
        password_unlock_entry.set_text("")
        composite_unlock_entry.set_text("")

    def show_unlock_failed_revealer(self):
        unlock_failed_box = self.builder.get_object("unlock_failed_box")

        unlock_failed_revealer = self.builder.get_object("unlock_failed_revealer")
        unlock_failed_revealer.set_reveal_child(not unlock_failed_revealer.get_reveal_child())
        revealer_timer = threading.Timer(3.0, GLib.idle_add, args=[self.hide_unlock_failed_revealer])
        revealer_timer.start()

    def hide_unlock_failed_revealer(self):
        unlock_failed_revealer = self.builder.get_object("unlock_failed_revealer")
        unlock_failed_revealer.set_reveal_child(not unlock_failed_revealer.get_reveal_child())

    def set_last_used_unlock_method(self, method):
        if passwordsafe.config_manager.get_remember_unlock_method() is True:
            passwordsafe.config_manager.set_unlock_method(method)
