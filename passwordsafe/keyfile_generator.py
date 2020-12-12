# SPDX-License-Identifier: GPL-3.0-only
import secrets
from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes
from gi.repository import GLib


def create_random_data(bytes_buffer):
    return secrets.token_bytes(bytes_buffer)


def generate_keyfile(filepath, database_creation, instance, composite):
    key = get_random_bytes(32)
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(create_random_data(96))

    with open(filepath, "wb") as keyfile:
        for data in (cipher.nonce, tag, ciphertext):
            keyfile.write(data)

    if database_creation is True:
        if composite is False:
            instance.database_manager.password = None

        instance.database_manager.set_database_keyfile(str(filepath))
        instance.database_manager.save_database()
        GLib.idle_add(instance.success_page)
    else:
        GLib.idle_add(instance.keyfile_generated)
