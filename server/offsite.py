"""The protected copy outside this PC (Solo plan, factory D1): the shop's backups, locked with the owner's paper phrase, written to a folder
that leaves the PC (a OneDrive or Google Drive folder that syncs to the internet, or a USB stick), and opened again on another PC.

- Standard library only. The phrase makes two keys (PBKDF2-SHA256); the copy is compressed, then encrypted with a keystream from keyed
  BLAKE2b (a PRF in counter mode, a fresh random nonce per file), then sealed with a keyed-BLAKE2b tag over the header and the body
  (encrypt-then-MAC). A changed byte, a wrong phrase or a cut file is refused before anything is written.
- The phrase is the customer's: printed once on paper, kept on this PC (the PC already holds the plain shop), never sent anywhere.
  Lose the paper and the PC together, and nobody can open the copies: not the company either.
- Versioned: every copy is a new file `alstore-YYYYMMDD-HHMMSS.alstore`; the oldest beyond `keep` are removed. Nothing is ever overwritten.
- A folder that cannot be reached never stops a sale or the PC's own backups: the failure is kept and shown on the Backups page.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import string
import struct
import zlib
from datetime import datetime, timedelta, timezone

import ids

MAGIC = b'AL-STORE SEALED BACKUP\n'
FORMAT = 1
ITERATIONS = 200_000
NAME = re.compile(r'^alstore-(\d{8}-\d{6})\.alstore$')
FOLDER = 'Al-Store-Backup'
KEEP = 30
MAX_HEADER = 4096
MAX_PLAIN = 2 * 1024 ** 3  # a shop database is tens of MB; anything claiming more than 2 GB is not ours
ALPHABET = ''.join(c for c in string.ascii_uppercase + string.digits if c not in 'O0I1L')  # nothing a person misreads on paper


class SealError(ValueError):
    """`key` is a dictionary key: err.offsiteNotOurs, err.offsitePhrase, err.offsiteBroken."""

    def __init__(self, key, text):
        super().__init__(text)
        self.key = key


def new_phrase():
    """Six groups of four (about 120 bits): strong enough that nobody guesses it, short enough to copy from paper."""
    raw = ''.join(secrets.choice(ALPHABET) for _ in range(24))
    return '-'.join(raw[i:i + 4] for i in range(0, 24, 4))


def normal(phrase):
    """What the person typed, as the program compares it: spaces, dashes and letter case do not matter; Arabic digits read as digits."""
    phrase = str(phrase or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789'))
    return ''.join(ch for ch in phrase.upper() if ch.isalnum() and ch.isascii())


def new_salt():
    return base64.b64encode(secrets.token_bytes(16)).decode()


def _keys(phrase, salt_b64, iterations):
    material = hashlib.pbkdf2_hmac('sha256', normal(phrase).encode(), base64.b64decode(salt_b64), int(iterations), 64)
    return material[:32], material[32:]


def _xor(key, nonce, data):
    """Keystream XOR: block i of the stream is BLAKE2b(key, nonce || i), 64 bytes each. Encrypts and decrypts."""
    out = bytearray()
    step = 64 * 1024
    for start in range(0, len(data), step):
        chunk = data[start:start + step]
        first = start // 64
        stream = b''.join(hashlib.blake2b(nonce + struct.pack('>Q', first + i), key=key, digest_size=64).digest()
                          for i in range((len(chunk) + 63) // 64))
        out += (int.from_bytes(chunk, 'big') ^ int.from_bytes(stream[:len(chunk)], 'big')).to_bytes(len(chunk), 'big')
    return bytes(out)


def _tag(key, framed, body):
    mac = hashlib.blake2b(key=key, digest_size=32)
    mac.update(framed)
    mac.update(body)
    return mac.digest()


def stamp_name(folder):
    moment = ids.utcnow().astimezone()
    while True:
        name = f'alstore-{moment.strftime("%Y%m%d-%H%M%S")}.alstore'
        if not os.path.exists(os.path.join(folder, name)):
            return name
        moment += timedelta(seconds=1)


def seal(db_path, folder, phrase, salt, org_id, keep=KEEP):
    """Locks the database file `db_path` (a checked backup, never the live file) into a new versioned file in `folder`."""
    with open(db_path, 'rb') as f:
        plain = f.read()
    nonce = secrets.token_bytes(16)
    header = json.dumps({'format': FORMAT, 'product': 'al-store', 'org_id': org_id, 'made_at': ids.iso(), 'kdf': 'pbkdf2-sha256',
                         'iterations': ITERATIONS, 'salt': salt, 'nonce': base64.b64encode(nonce).decode(), 'size': len(plain)},
                        sort_keys=True).encode()
    enc_key, mac_key = _keys(phrase, salt, ITERATIONS)
    body = _xor(enc_key, nonce, zlib.compress(plain, 6))
    framed = MAGIC + struct.pack('>I', len(header)) + header
    os.makedirs(folder, exist_ok=True)
    name = stamp_name(folder)
    path = os.path.join(folder, name)
    part = path + '.part'  # a copy cut short (USB pulled, sync folder full) never carries a copy's name
    try:
        with open(part, 'wb') as f:
            f.write(framed)
            f.write(body)
            f.write(_tag(mac_key, framed, body))
            f.flush()
            os.fsync(f.fileno())
        os.replace(part, path)
    except OSError:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    prune(folder, keep)
    return {'name': name, 'size': os.path.getsize(path), 'at': ids.iso()}


def peek(path):
    """The plain header of a sealed copy (which shop, when), without the phrase. None when the file is not a sealed Al-Store copy."""
    try:
        with open(path, 'rb') as f:
            head = f.read(len(MAGIC) + 4)
            if len(head) < len(MAGIC) + 4 or head[:len(MAGIC)] != MAGIC:
                return None
            size = struct.unpack('>I', head[len(MAGIC):])[0]
            if size > MAX_HEADER:
                return None
            header = json.loads(f.read(size).decode('utf-8'))
        if not isinstance(header, dict) or header.get('product') != 'al-store' or header.get('format') != FORMAT:
            return None
        return header
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def unseal(path, phrase, out_path):
    """Checks the tag with the phrase, then writes the shop's database to `out_path`. Refuses before writing anything when the phrase is
    wrong or a single byte changed. Returns the header."""
    header = peek(path)
    if header is None:
        raise SealError('err.offsiteNotOurs', 'This file is not a protected Al-Store copy.')
    with open(path, 'rb') as f:
        data = f.read()
    framed_len = len(MAGIC) + 4 + struct.unpack('>I', data[len(MAGIC):len(MAGIC) + 4])[0]
    if len(data) < framed_len + 32:
        raise SealError('err.offsiteBroken', 'This copy is incomplete.')
    framed, body, tag = data[:framed_len], data[framed_len:-32], data[-32:]
    try:
        enc_key, mac_key = _keys(phrase, header['salt'], header['iterations'])
        nonce = base64.b64decode(header['nonce'])
    except (KeyError, ValueError, TypeError):
        raise SealError('err.offsiteBroken', 'This copy is damaged.')
    if not normal(phrase) or not hmac.compare_digest(_tag(mac_key, framed, body), tag):
        # one tag for both causes: a wrong phrase and a changed byte cannot be told apart, and the person is told both
        raise SealError('err.offsitePhrase', 'The phrase is wrong, or the copy was changed.')
    try:
        unzip = zlib.decompressobj()
        plain = unzip.decompress(_xor(enc_key, nonce, body), MAX_PLAIN)
        if unzip.unconsumed_tail or len(plain) != header.get('size'):
            raise SealError('err.offsiteBroken', 'This copy is damaged.')
    except zlib.error:
        raise SealError('err.offsiteBroken', 'This copy is damaged.')
    part = out_path + '.part'
    with open(part, 'wb') as f:
        f.write(plain)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, out_path)
    return header


def db_facts(path):
    """What a restored file says about itself: its shop, schema and kind (real or practice). None when it is not a shop database."""
    try:
        c = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                return None
            meta = dict(c.execute('SELECT key, value FROM meta').fetchall())
            shop = c.execute("SELECT value FROM settings WHERE key = 'shop_name'").fetchone()
        finally:
            c.close()
    except sqlite3.Error:
        return None
    if 'schema' not in meta:
        return None
    try:
        name = json.loads(shop[0]) if shop else ''
    except (TypeError, ValueError):
        name = shop[0] if shop else ''
    return {'org_id': meta.get('org_id'), 'schema': int(meta['schema']), 'kind': meta.get('shop_kind', 'real'),
            'shop_name': name if isinstance(name, str) else ''}


def listing(folder):
    if not folder or not os.path.isdir(folder):
        return []
    out = []
    for name in sorted(os.listdir(folder), reverse=True):
        if NAME.match(name):
            path = os.path.join(folder, name)
            try:
                out.append({'name': name, 'size': os.path.getsize(path),
                            'mtime': ids.iso(datetime.fromtimestamp(os.path.getmtime(path), timezone.utc))})
            except OSError:
                pass
    return out


def age_hours(folder):
    newest = None
    for item in listing(folder):
        try:
            when = os.path.getmtime(os.path.join(folder, item['name']))
        except OSError:
            continue
        newest = when if newest is None else max(newest, when)
    return None if newest is None else round((ids.utcnow().timestamp() - newest) / 3600, 1)


def prune(folder, keep=KEEP):
    for old in listing(folder)[max(int(keep), 3):]:  # never fewer than three versions
        try:
            os.remove(os.path.join(folder, old['name']))
        except OSError:
            pass


def places():
    """Folders on this PC that leave it: OneDrive and Google Drive folders (they sync to the internet) and other drives (a USB stick).
    `STORE_OFFSITE_PLACES` (paths joined by the OS path separator) replaces the search, for tests and for a technician."""
    override = os.environ.get('STORE_OFFSITE_PLACES')
    if override is not None:
        return [{'kind': 'folder', 'base': p} for p in override.split(os.pathsep) if p and os.path.isdir(p)]
    found, seen = [], set()

    def add(kind, base):
        if base and os.path.isdir(base) and os.path.realpath(base).lower() not in seen:
            seen.add(os.path.realpath(base).lower())
            found.append({'kind': kind, 'base': base})

    for var in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
        add('onedrive', os.environ.get(var))
    profile = os.environ.get('USERPROFILE') or os.path.expanduser('~')
    add('gdrive', os.path.join(profile, 'Google Drive'))
    add('gdrive', os.path.join(profile, 'My Drive'))
    if os.name == 'nt':
        system = (os.environ.get('SystemDrive') or 'C:').upper()[:1]
        for letter in 'DEFGHIJKLMNOPQRSTUVWXYZ':
            if letter == system:
                continue
            root = f'{letter}:\\'
            if os.path.isdir(os.path.join(root, 'My Drive')):
                add('gdrive', os.path.join(root, 'My Drive'))
            elif os.path.isdir(root):
                add('drive', root)
    return found


def inside_places(path, extra=()):
    """The real path of `path` when it lies inside a place that leaves this PC (or inside `extra`), else None. Every folder and file the
    person names goes through here first: the program never reads or writes anywhere else for the protected copy."""
    if not isinstance(path, str) or not path or '\0' in path:
        return None
    real = os.path.realpath(path)
    for base in [p['base'] for p in places()] + [e for e in extra if e]:
        root = os.path.realpath(base)
        if real == root or real.startswith(root.rstrip('\\/') + os.sep):
            return real
    return None


def cloud_bases():
    return [p['base'] for p in places() if p['kind'] in ('onedrive', 'gdrive')]


def same_disk(folder, home):
    """True when `folder` sits on the PC's own disk and is not a folder that syncs out: then it does not protect against a dead PC."""
    try:
        real = os.path.realpath(folder)
        for base in cloud_bases():
            base = os.path.realpath(base)
            if os.path.commonpath([real, base]) == base:
                return False
        probe = real
        while not os.path.exists(probe):
            probe = os.path.dirname(probe)
        return os.stat(probe).st_dev == os.stat(home).st_dev
    except (OSError, ValueError):
        return False


def find_copies(extra=()):
    """Sealed copies the person can restore on this PC: in the known places (and their Al-Store-Backup folder), newest first."""
    out, seen = [], set()
    folders = list(extra) + [p['base'] for p in places()] + [os.path.join(p['base'], FOLDER) for p in places()]
    for folder in folders:
        if not folder or not os.path.isdir(folder) or os.path.realpath(folder) in seen:
            continue
        seen.add(os.path.realpath(folder))
        for item in listing(folder)[:10]:
            path = os.path.join(folder, item['name'])
            header = peek(path)
            if header:
                out.append({'path': path, 'name': item['name'], 'size': item['size'], 'made_at': header.get('made_at') or item['mtime']})
    out.sort(key=lambda x: x['made_at'], reverse=True)
    return out[:20]
