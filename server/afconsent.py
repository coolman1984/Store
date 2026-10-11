# Vendored from Apps-Factory packages/af-consent 0.1.1 - do not edit here.
# Update with: python scripts/vendor_consent.py <product repo> (from the Apps-Factory checkout)
"""af-consent: the factory's consent records (standard library only, one file, vendorable).

Two levels (PRIV-01, PRIV-02):
  * installation - the customer's owner agrees once for the whole installation (Settings, or the first-run card);
  * person       - each person who signs in is asked once: «أوافق حتى يستطيع [vendor] مساعدتي عن بُعد» [أوافق] [لا أوافق].
Tracking for a person runs only when BOTH agreed. A decline means zero events for that person. Withdrawing (Settings
«الخصوصية والمساعدة») is recorded and the product deletes that person's pending events (af_telemetry.purge_subject).
Problem reports the person writes and previews (fb.*) are allowed without tracking consent (owner decision 2026-10-09).
The support window (SUP-02) stays a separate, time-boxed consent and is not covered here.

Every decision is kept (append-only) with the time, the exact text id the person saw, its language and who recorded it.

    consent = Consent(db)                         # db: sqlite3 connection (or any DB-API with ? params)
    db.executescript(SQL)                         # in the product's forward-only migrations
    consent.record('person', user_id, 'agree', 'consent.help.remote.ar.v1', 'ar', by=user_id)
    consent.allowed(user_id)                      # True only when installation and person agreed
    prompt('ar', vendor_name(settings, DEVELOPER))
"""
from datetime import datetime, timezone

__version__ = '0.1.1'

FALLBACK_VENDOR = 'coolman1984'
SCOPES = {'install', 'person'}
DECISIONS = {'agree', 'decline', 'withdraw'}
INSTALL = ''   # subject of installation-level records

TEXTS = {
    'consent.help.remote.ar.v1': {
        'lang': 'ar', 'text': 'أوافق حتى يستطيع {vendor} مساعدتي عن بُعد.', 'agree': 'أوافق', 'decline': 'لا أوافق',
        'more': 'عند الموافقة يصل إلى {vendor} عدد مرات استخدام الصفحات والأخطاء وأرقام تعريف فقط. '
                'لا تصل كلمات السر ولا ما تكتبه ولا صور الشاشة ولا بيانات العملاء أو المبالغ. '
                'تستطيع تغيير اختيارك في أي وقت من «الخصوصية والمساعدة».',
        'recorded': {'agree': 'وافق', 'decline': 'لم يوافق', 'withdraw': 'سحب الموافقة'}},
    'consent.help.remote.en.v1': {
        'lang': 'en', 'text': 'I agree so that {vendor} can help me remotely.', 'agree': 'I agree', 'decline': 'I do not agree',
        'more': 'If you agree, {vendor} receives page-use counts, errors and ID numbers only. Passwords, what you type, '
                'screenshots, customer data and amounts are never sent. You can change this at any time in '
                '"Privacy and help".',
        'recorded': {'agree': 'agreed', 'decline': 'declined', 'withdraw': 'withdrew'}},
}
CURRENT = {'ar': 'consent.help.remote.ar.v1', 'en': 'consent.help.remote.en.v1'}

SQL = """CREATE TABLE IF NOT EXISTS consent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK (scope IN ('install', 'person')),
    subject TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('agree', 'decline', 'withdraw')),
    text_id TEXT NOT NULL,
    lang TEXT NOT NULL,
    by_user TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS consent_log_subject ON consent_log (scope, subject, id);"""


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def vendor_name(settings=None, developer=None):
    """The one name shown in the prompt: settings['vendor_display_name'] if set, else the product's DEVELOPER
    (what the About box already shows), else coolman1984."""
    for v in ((settings or {}).get('vendor_display_name'), developer):
        if isinstance(v, str) and v.strip():
            return v.strip()[:60]
    return FALLBACK_VENDOR


def prompt(lang, vendor):
    """The exact prompt for the first sign-in card. Both buttons are equal; neither is pre-selected."""
    tid = CURRENT.get(lang, CURRENT['ar'])
    t = TEXTS[tid]
    return {'text_id': tid, 'lang': t['lang'], 'text': t['text'].format(vendor=vendor), 'more': t['more'].format(vendor=vendor),
            'agree': t['agree'], 'decline': t['decline']}


class Consent:
    def __init__(self, conn, on_change=None):
        self.db = conn
        self.on_change = on_change   # callback(scope, subject, decision): purge the outbox on decline/withdraw

    def record(self, scope, subject, decision, text_id, lang, by, at=None):
        if scope not in SCOPES or decision not in DECISIONS:
            raise ValueError('bad scope or decision')
        if text_id not in TEXTS or TEXTS[text_id]['lang'] != lang:
            raise ValueError('unknown consent text')
        subject = INSTALL if scope == 'install' else str(subject or '')
        if scope == 'person' and not subject:
            raise ValueError('person consent needs the person id')
        self.db.execute('INSERT INTO consent_log (scope, subject, decision, text_id, lang, by_user, at) VALUES (?,?,?,?,?,?,?)',
                        (scope, subject, decision, text_id, lang, str(by), at or now_iso()))
        if self.on_change and decision != 'agree':
            self.on_change(scope, subject, decision)
        return self.current(scope, subject)

    def current(self, scope, subject=INSTALL):
        row = self.db.execute('SELECT decision, text_id, lang, by_user, at FROM consent_log WHERE scope = ? AND subject = ? '
                              'ORDER BY id DESC LIMIT 1', (scope, INSTALL if scope == 'install' else str(subject))).fetchone()
        if not row:
            return None
        return {'decision': row[0], 'text_id': row[1], 'lang': row[2], 'by': row[3], 'at': row[4],
                'label': TEXTS[row[1]]['recorded'][row[0]]}

    def install_allowed(self):
        c = self.current('install')
        return bool(c and c['decision'] == 'agree')

    def person_allowed(self, user_id):
        c = self.current('person', user_id)
        return bool(c and c['decision'] == 'agree')

    def allowed(self, user_id=None):
        """Person-level tracking: installation AND person agreed. Installation-level events: user_id=None."""
        if not self.install_allowed():
            return False
        return True if user_id is None else self.person_allowed(user_id)

    def needs_prompt(self, user_id):
        """Ask at sign-in only when the installation agreed and this person never answered."""
        return self.install_allowed() and self.current('person', user_id) is None

    def history(self, scope=None, subject=None, limit=200):
        q, args = 'SELECT scope, subject, decision, text_id, lang, by_user, at FROM consent_log', []
        if scope:
            q += ' WHERE scope = ?' + (' AND subject = ?' if subject is not None else '')
            args = [scope] + ([str(subject)] if subject is not None else [])
        rows = self.db.execute(q + ' ORDER BY id DESC LIMIT ?', (*args, int(limit))).fetchall()
        return [dict(zip(('scope', 'subject', 'decision', 'text_id', 'lang', 'by', 'at'), r)) for r in rows]

    def status(self, user_id):
        """What Settings «الخصوصية والمساعدة» shows."""
        return {'install': self.current('install'), 'person': self.current('person', user_id),
                'tracking': self.allowed(user_id), 'feedback_always_allowed': True}
