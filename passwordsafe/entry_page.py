# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import typing
from gettext import gettext as _
from typing import List

from gi.repository import Gio, GLib, GObject, Gtk

from passwordsafe.attachment_warning_dialog import AttachmentWarningDialog
from passwordsafe.color_widget import ColorEntryRow
from passwordsafe.history_buffer import HistoryEntryBuffer, HistoryTextBuffer
from passwordsafe.notes_dialog import NotesDialog
from passwordsafe.password_entry_row import PasswordEntryRow
from passwordsafe.safe_element import ICONS

if typing.TYPE_CHECKING:
    from passwordsafe.safe_element import SafeEntry

if typing.TYPE_CHECKING:
    from pykeepass.attachment import Attachment


@Gtk.Template(resource_path="/org/gnome/PasswordSafe/entry_page.ui")
class EntryPage(Gtk.ScrolledWindow):
    # pylint: disable=too-many-public-methods

    __gtype_name__ = "EntryPage"

    _filechooser = None

    name_property_value_entry = Gtk.Template.Child()

    username_property_value_entry = Gtk.Template.Child()

    password_property_box = Gtk.Template.Child()

    url_property_box = Gtk.Template.Child()
    url_property_value_entry = Gtk.Template.Child()

    notes_property_box = Gtk.Template.Child()
    notes_property_value_entry = Gtk.Template.Child()

    color_property_box = Gtk.Template.Child()

    icon_entry_box = Gtk.Template.Child()

    attachment_property_box = Gtk.Template.Child()
    attachment_list_box = Gtk.Template.Child()

    attributes_key_entry = Gtk.Template.Child()
    attribute_list_box = Gtk.Template.Child()
    attributes_property_box = Gtk.Template.Child()
    attributes_value_entry = Gtk.Template.Child()

    show_all_row = Gtk.Template.Child()

    attribute_property_row_list: List[Gtk.ListBoxRow] = []

    def __init__(self, u_d, add_all):
        super().__init__()

        self.unlocked_database = u_d
        self.toggeable_widget_list = [self.url_property_box,
                                      self.notes_property_box,
                                      self.attachment_property_box,
                                      self.attributes_property_box]

        self.insert_entry_properties_into_listbox(add_all)

        safe_entry: SafeEntry = self.unlocked_database.current_element
        safe_entry.connect("updated", self._on_safe_entry_updated)

    def insert_entry_properties_into_listbox(self, add_all):
        # pylint: disable=too-many-locals
        # pylint: disable=too-many-branches
        # pylint: disable=too-many-statements
        safe_entry: SafeEntry = self.unlocked_database.current_element

        # Create the name_property_row
        self.name_property_value_entry.set_buffer(HistoryEntryBuffer([]))

        safe_entry.bind_property(
            "name", self.name_property_value_entry, "text",
            GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.BIDIRECTIONAL
        )
        self.name_property_value_entry.grab_focus()

        # Username
        self.username_property_value_entry.set_buffer(HistoryEntryBuffer([]))
        safe_entry.bind_property(
            "username", self.username_property_value_entry, "text",
            GObject.BindingFlags.SYNC_CREATE
            | GObject.BindingFlags.BIDIRECTIONAL)
        self.unlocked_database.bind_accelerator(
            self.username_property_value_entry,
            "<primary><Shift>b",
            signal="copy-clipboard")

        value = safe_entry.username != ""

        # Password
        self.password_property_box.add(PasswordEntryRow(
            self.unlocked_database))

        # Url
        self.url_property_value_entry.set_buffer(HistoryEntryBuffer([]))
        safe_entry.bind_property(
            "url", self.url_property_value_entry, "text",
            GObject.BindingFlags.SYNC_CREATE
            | GObject.BindingFlags.BIDIRECTIONAL)
        self.show_row(self.url_property_box, safe_entry.url, add_all)

        # Notes
        self.notes_property_value_entry.get_style_context().add_class("codeview")

        textbuffer = HistoryTextBuffer([])
        safe_entry.bind_property(
            "notes", textbuffer, "text",
            GObject.BindingFlags.SYNC_CREATE
            | GObject.BindingFlags.BIDIRECTIONAL)
        self.notes_property_value_entry.set_buffer(textbuffer)
        self.show_row(self.notes_property_box, safe_entry.notes, add_all)

        # Color
        self.color_property_box.add(ColorEntryRow(
            self.unlocked_database, safe_entry))

        # Icons
        icon_builder = Gtk.Builder()
        entry_icon = safe_entry.props.icon
        for icon_nr, icon in ICONS.items():
            if not icon.visible:
                continue

            icon_builder.add_from_resource(
                "/org/gnome/PasswordSafe/icon_widget.ui")
            btn = icon_builder.get_object("icon_button")
            img = icon_builder.get_object("image")
            img.props.icon_name = icon.name

            if entry_icon == icon:
                self.icon_entry_box.select_child(btn)

            btn.set_name(icon_nr)
            self.icon_entry_box.add(btn)

        self.icon_entry_box.connect(
            "selected-children-changed", self.on_entry_icon_button_toggled
        )

        # Attachments
        for attachment in safe_entry.attachments:
            self.add_attachment_row(attachment)

        self.show_row(self.attachment_property_box, safe_entry.attachments, add_all)

        # Attributes
        self.show_row(self.attributes_property_box, safe_entry.attributes, add_all)

        for key, value in safe_entry.attributes.items():
            self.add_attribute_property_row(key, value)

        for widget in self.toggeable_widget_list:
            if not widget.get_visible():
                self.show_all_row.set_visible(True)
                break

    def add_attribute_property_row(self, key, value):
        """Add an attribute to the attributes list view.

        :param str key: property name
        :param str value: property value
        """
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/attribute_entry_row.ui")

        attribute_row = builder.get_object("attribute_row")
        attribute_property_name_label = builder.get_object("attribute_property_name_label")
        attribute_key_edit_button = builder.get_object("attribute_key_edit_button")
        attribute_value_entry = builder.get_object("attribute_value_entry")
        attribute_value_entry.set_buffer(HistoryEntryBuffer([]))
        attribute_remove_button = builder.get_object("attribute_remove_button")

        attribute_property_name_label.set_text(key)
        if value is not None:
            attribute_value_entry.set_text(value)
        attribute_remove_button.connect("clicked", self.on_attribute_remove_button_clicked, key)
        attribute_key_edit_button.connect("clicked", self.on_attribute_key_edit_button_clicked)
        attribute_value_entry.connect("changed", self.on_attributes_value_entry_changed, key)

        self.attribute_list_box.add(attribute_row)
        attribute_row.show_all()
        self.attribute_property_row_list.append(attribute_row)

    #
    # Events
    #

    @Gtk.Template.Callback()
    def on_show_all_properties_button_clicked(self, _widget):
        self.unlocked_database.start_database_lock_timer()

        for widget in self.toggeable_widget_list:
            widget.set_visible(True)

        self.show_all_row.set_visible(False)

    @Gtk.Template.Callback()
    def on_notes_detach_button_clicked(self, _button):
        self.unlocked_database.start_database_lock_timer()
        safe_entry = self.unlocked_database.current_element
        NotesDialog(self.unlocked_database, safe_entry).present()

    def on_entry_icon_button_toggled(self, flowbox):
        if not flowbox.get_selected_children():
            return

        selected_row = flowbox.get_selected_children()[0]
        icon = selected_row.get_name()

        safe_entry = self.unlocked_database.current_element
        safe_entry.props.icon = icon

    @Gtk.Template.Callback()
    def on_link_secondary_button_clicked(self, widget, _position, _eventbutton):
        self.unlocked_database.start_database_lock_timer()
        Gtk.show_uri_on_window(self.unlocked_database.window, widget.get_text(), Gtk.get_current_event_time())

    #
    # Additional Attributes
    #

    @Gtk.Template.Callback()
    def on_attributes_add_button_clicked(self, _widget):
        safe_entry: SafeEntry = self.unlocked_database.current_element

        key = self.attributes_key_entry.get_text()
        value = self.attributes_value_entry.get_text()

        if key == "" or key is None:
            self.attributes_key_entry.get_style_context().add_class("error")
            return

        if safe_entry.has_attribute(key):
            self.attributes_key_entry.get_style_context().add_class("error")
            self.unlocked_database.window.notify(_("Attribute key already exists"))
            return

        self.attributes_key_entry.get_style_context().remove_class("error")

        self.attributes_key_entry.set_text("")
        self.attributes_value_entry.set_text("")

        safe_entry.set_attribute(key, value)
        self.add_attribute_property_row(key, value)

    def on_attribute_remove_button_clicked(self, button, key):
        safe_entry: SafeEntry = self.unlocked_database.current_element

        attribute_row = button.get_parent().get_parent()
        safe_entry.delete_attribute(key)
        self.attribute_list_box.remove(attribute_row)

    def on_attributes_value_entry_changed(self, widget, key):
        safe_entry = self.unlocked_database.current_element
        safe_entry.set_attribute(key, widget.get_text())

    def on_attribute_key_edit_button_clicked(self, button):
        safe_entry: SafeEntry = self.unlocked_database.current_element
        parent = button.get_parent()

        parent = button.get_parent().get_parent().get_parent()
        key = button.get_children()[0].get_label()

        key_entry = Gtk.Entry()
        key_entry.set_visible(True)

        key_entry.connect(
            "activate", self.on_key_entry_activated, safe_entry, key, button, parent)
        key_entry.set_text(key)

        attribute_entry_box = button.get_parent()
        attribute_entry_box.remove(button)
        attribute_entry_box.add(key_entry)
        attribute_entry_box.reorder_child(key_entry, 0)
        key_entry.grab_focus()

    def on_key_entry_activated(
            self, widget: Gtk.Entry, safe_entry: SafeEntry, key: str,
            button: Gtk.Button, parent: Gtk.Box) -> None:
        # pylint: disable=too-many-arguments
        new_key: str = widget.props.text
        if not new_key:
            widget.get_style_context().add_class("error")
            return

        if new_key == key:
            attribute_entry_box = widget.get_parent()
            attribute_entry_box.remove(widget)
            attribute_entry_box.add(button)
            attribute_entry_box.reorder_child(button, 0)
            return

        if safe_entry.has_attribute(new_key):
            widget.get_style_context().add_class("error")
            self.unlocked_database.window.notify(_("Attribute key already exists"))
            return

        safe_entry.set_attribute(new_key, safe_entry.props.attributes[key])
        safe_entry.delete_attribute(key)

        button.get_children()[0].set_text(new_key)
        parent.set_name(new_key)

        attribute_entry_box = widget.get_parent()
        attribute_entry_box.remove(widget)
        attribute_entry_box.add(button)
        attribute_entry_box.reorder_child(button, 0)

    #
    # Attachment Handling
    #

    @Gtk.Template.Callback()
    def on_attachment_list_box_activated(self, _widget, list_box_row):
        if list_box_row.get_name() == "AddAttachmentRow":
            self.on_add_attachment_row_clicked()
        else:
            safe_entry: SafeEntry = self.unlocked_database.current_element
            attachment = safe_entry.get_attachment(list_box_row.get_name())
            self.on_attachment_row_clicked(attachment)

    def on_add_attachment_row_clicked(self):
        self.unlocked_database.start_database_lock_timer()
        select_dialog = Gtk.FileChooserNative.new(
            # NOTE: Filechooser title for selecting attachment file
            _("Select attachment"), self.unlocked_database.window, Gtk.FileChooserAction.OPEN,
            _("_Add"), None)
        select_dialog.set_modal(True)
        select_dialog.set_select_multiple(True)

        # We need to hold a reference, otherwise the app crashes.
        self._filechooser = select_dialog
        select_dialog.connect("response", self._on_select_filechooser_response)
        select_dialog.show()

    def _on_select_filechooser_response(self,
                                        dialog: Gtk.Dialog,
                                        response: Gtk.ResponseType) -> None:
        self._filechooser = None
        if response == Gtk.ResponseType.ACCEPT:
            safe_entry: SafeEntry = self.unlocked_database.current_element
            for attachment in dialog.get_files():
                uri = attachment.get_uri()
                attachment = Gio.File.new_for_uri(uri)
                byte_buffer = attachment.load_bytes()[0].get_data()
                filename = attachment.get_basename()
                new_attachment = safe_entry.add_attachment(byte_buffer, filename)
                self.add_attachment_row(new_attachment)

    def add_attachment_row(self, attachment):
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/PasswordSafe/attachment_entry_row.ui")

        attachment_row = builder.get_object("attachment_row")
        attachment_row.set_name(str(attachment.id))
        attachment_row.set_title(attachment.filename)
        builder.get_object("attachment_download_button").connect(
            "clicked", self.on_attachment_download_button_clicked, attachment
        )
        builder.get_object("attachment_delete_button").connect(
            "clicked",
            self.on_attachment_delete_button_clicked,
            attachment,
            attachment_row,
        )

        self.attachment_list_box.insert(attachment_row, len(self.attachment_list_box) - 1)

    def on_attachment_row_clicked(self, attachment):
        AttachmentWarningDialog(self, attachment).present()

    def on_attachment_download_button_clicked(self, _button, attachment):
        save_dialog = Gtk.FileChooserNative.new(
            # NOTE: Filechooser title for downloading an attachment
            _("Save attachment"), self.unlocked_database.window, Gtk.FileChooserAction.SAVE,
            _("_Save"), None)
        save_dialog.set_current_name(attachment.filename)
        save_dialog.set_modal(True)

        self._filechooser = save_dialog
        save_dialog.connect("response", self._on_save_filechooser_response, attachment)
        save_dialog.show()

    def _on_save_filechooser_response(self,
                                      dialog: Gtk.Dialog,
                                      response: Gtk.ResponseType,
                                      attachment: Attachment) -> None:
        self._filechooser = None
        if response == Gtk.ResponseType.ACCEPT:
            safe_entry: SafeEntry = self.unlocked_database.current_element
            bytes_buffer = safe_entry.get_attachment_content(attachment)
            self.save_to_disk(dialog.get_file().get_path(), bytes_buffer)

    def on_attachment_delete_button_clicked(
            self, _button, attachment_to_delete, attachment_row):
        safe_entry: SafeEntry = self.unlocked_database.current_element
        safe_entry.delete_attachment(attachment_to_delete)

        self.attachment_list_box.remove(attachment_row)

    #
    # Helper
    #

    def save_to_disk(self, filepath, byte_buffer):
        file = Gio.File.new_for_path(filepath)
        stream = Gio.File.replace(
            file, None, False,
            Gio.FileCreateFlags.PRIVATE
            | Gio.FileCreateFlags.REPLACE_DESTINATION, None)
        Gio.OutputStream.write_bytes(stream, GLib.Bytes.new(byte_buffer), None)
        stream.close()

    @Gtk.Template.Callback()
    def _on_copy_secondary_button_clicked(
            self, widget, _position=None, _eventbutton=None):
        self.unlocked_database.send_to_clipboard(
            widget.get_text(),
            _("Username copied to clipboard"),
        )

    def show_row(self, row: Gtk.ListBoxRow, non_empty: bool, add_all: bool) -> None:
        if non_empty or add_all:
            row.set_visible(True)
        else:
            row.set_visible(False)

    def _on_safe_entry_updated(self, _safe_entry: SafeEntry) -> None:
        self.unlocked_database.start_database_lock_timer()
