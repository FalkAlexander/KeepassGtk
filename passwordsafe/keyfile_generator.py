from gi.repository import GLib
from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes
import secrets


def create_random_data(bytes_buffer):
    return secrets.token_bytes(bytes_buffer)


def generate_keyfile(filepath, database_creation, instance, composite):
    key = get_random_bytes(32)
    cipher = AES.new(key, AES.MODE_EAX)
    ciphertext, tag = cipher.encrypt_and_digest(create_random_data(96))

    keyfile = open(filepath, "wb")
    [keyfile.write(x) for x in (cipher.nonce, tag, ciphertext)]
    keyfile.close()

    if database_creation is True:
        if composite is False:
            instance.database_manager.set_database_password(None)

        instance.database_manager.set_database_keyfile(str(filepath))
        instance.database_manager.save_database()
        GLib.idle_add(instance.set_database_keyfile)
    else:
        GLib.idle_add(instance.keyfile_generated)
