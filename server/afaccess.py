# Vendored from Apps-Factory packages/af-access 0.1.1 af_access.py - do not edit here.
# Update with: python scripts/vendor_access.py <product repo> (from the Apps-Factory checkout)
"""af-access: the factory's access-and-administration gate (standard library only, one file, vendorable).

A product describes its permissions as a *catalogue* (plain JSON-able dict, see README.md). This module

  * checks the catalogue against the factory rules learned in BAMS (Mr.Ayman-HR) - `check(catalogue)`;
  * gives the runtime guards every product needs when an administrator changes people or profiles -
    `admin_safety(...)`, `effective(...)`, `perm_diff(...)`, `matching_profile(...)`;
  * prints the "who can do what" matrix for the owner - `matrix(catalogue)`.

    python af_access.py check catalogue.json        # exit 1 on any error
    python af_access.py matrix catalogue.json [ar]  # Markdown table: profiles x permissions

It never decides a request by itself: every product still checks every permission on its server for every request.
"""
import json
import re
import sys

__version__ = '0.1.1'

ID_RE = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$')
KINDS = {'page', 'action', 'field', 'admin'}
RESERVED_PROFILE_NAMES = {'custom', 'مخصص'}
SIGNED_IN = '*'  # a page anybody who is signed in may open (home, help)


class Finding:
    def __init__(self, level, code, where, message):
        self.level, self.code, self.where, self.message = level, code, where, message

    def __repr__(self):
        return f'{self.level.upper()} {self.code} [{self.where}] {self.message}'


def _labels(item):
    if isinstance(item.get('labels'), dict):
        return item['labels']
    return {'en': item['label']} if isinstance(item.get('label'), str) else {}


def permissions(cat):
    """[(permission dict, group dict)] in catalogue order."""
    return [(p, g) for g in cat.get('groups', []) for p in g.get('permissions', [])]


def admin_perms(cat):
    return {p['id'] for p, g in permissions(cat) if g.get('admin')}


def all_perms(cat):
    return [p['id'] for p, _ in permissions(cat)]


def check(cat):
    """Every rule broken by the catalogue, as Findings (level 'error' or 'warning')."""
    out = []

    def bad(code, where, msg, level='error'):
        out.append(Finding(level, code, where, msg))

    langs = cat.get('languages') or ['en']
    perms = permissions(cat)
    ids = [p.get('id') for p, _ in perms]
    known = set(ids)
    manage = cat.get('manage', 'users.manage')

    for p, g in perms:
        pid = p.get('id')
        if not isinstance(pid, str) or not ID_RE.match(pid):
            bad('perm-id', str(pid), 'Permission ids are lower-case words joined by dots, e.g. "sales.return".')
        if ids.count(pid) > 1:
            bad('perm-duplicate', str(pid), 'The same permission is listed twice.')
        if p.get('kind', 'action') not in KINDS:
            bad('perm-kind', str(pid), f'kind must be one of {sorted(KINDS)}.')
        for lang in langs:
            if not str(_labels(p).get(lang) or '').strip():
                bad('label-missing', f'{pid}:{lang}', 'Every permission needs a plain-words label in every language of the product.')
        for r in p.get('requires', []):
            if r not in known:
                bad('requires-unknown', str(pid), f'requires "{r}", which is not a permission.')
            elif r == pid:
                bad('requires-self', str(pid), 'A permission cannot require itself.')
    for g in cat.get('groups', []):
        for lang in langs:
            if not str(_labels(g).get(lang) or '').strip():
                bad('label-missing', f'group {g.get("id")}:{lang}', 'Every group needs a title in every language.')

    admin_groups = [g for g in cat.get('groups', []) if g.get('admin')]
    if len(admin_groups) != 1 or not admin_groups[0].get('permissions'):
        bad('admin-group', 'groups', 'Exactly one non-empty administrator group is needed (shown apart, never ticked by "select all").')
    admins = admin_perms(cat)
    if manage not in known:
        bad('manage-missing', manage, 'The right to manage people and permissions must be a permission.')
    elif manage not in admins:
        bad('manage-not-admin', manage, 'The right to manage people and permissions belongs in the administrator group.')

    # pages: route -> any-of permissions, or "*" for everybody signed in
    page_perms_used = set()
    for route, need in (cat.get('pages') or {}).items():
        if need == SIGNED_IN:
            continue
        if not isinstance(need, list) or not need:
            bad('page-unguarded', route, 'A page lists the permissions that open it, or "*" for everybody signed in.')
            continue
        for n in need:
            if n not in known:
                bad('page-unknown-perm', route, f'"{n}" is not a permission.')
            page_perms_used.add(n)
    if not any(p.get('kind') == 'page' for p, _ in perms):
        bad('no-page-perms', 'groups', 'Mark the permissions that open pages (kind "page"): one permission per page is the standard.')
    if not cat.get('pages'):
        bad('pages-missing', 'pages', 'Say which permission opens each page (route -> permissions), so the gate can prove every page is guarded.')
    if cat.get('pages'):
        for p, _ in perms:
            if p.get('kind') == 'page' and p['id'] not in page_perms_used:
                bad('page-perm-unused', p['id'], 'A page permission that opens no page: the tick would do nothing.', 'warning')

    # profiles
    profs = cat.get('profiles') or []
    locked = [p for p in profs if p.get('locked')]
    if len(locked) != 1:
        bad('locked-profile', 'profiles', 'Exactly one locked profile (the administrator) is needed, so there is always a way back in.')
    elif set(locked[0].get('perms', [])) != known:
        bad('locked-profile', locked[0].get('id'), 'The locked administrator profile must hold every permission.')
    seen_ids, seen_names = set(), {}
    requires = {p['id']: set(p.get('requires', [])) for p, _ in perms if isinstance(p.get('id'), str)}
    for pr in profs:
        pid = pr.get('id')
        if not isinstance(pid, str) or not pid.strip():
            bad('profile-id', str(pid), 'Every profile needs an id (text) so people can be linked to it.')
        if pid in seen_ids:
            bad('profile-duplicate', str(pid), 'Two profiles share an id.')
        seen_ids.add(pid)
        names = _labels(pr) or {'en': pr.get('name', '')}
        for lang in langs:
            if not str(names.get(lang) or '').strip():
                bad('label-missing', f'profile {pid}:{lang}', 'Every ready-made profile needs a name in every language.')
        for lang, name in names.items():
            key = (lang, str(name).strip().lower())
            if not key[1]:
                continue
            if key[1] in RESERVED_PROFILE_NAMES:
                bad('profile-reserved-name', str(pid), '"Custom" means "own set of ticks"; a profile cannot be called that.')
            if key in seen_names:
                bad('profile-duplicate', str(pid), f'Same name as profile "{seen_names[key]}".')
            seen_names[key] = pid
        held = set(pr.get('perms', []))
        for x in sorted(held - known):
            bad('profile-unknown-perm', str(pid), f'"{x}" is not a permission.')
        for x in sorted(held & known):
            for r in sorted(requires.get(x, set()) - held):
                bad('profile-missing-requires', str(pid), f'has "{x}" but not "{r}", which it needs to be usable.')
    if profs and not any(not admins.intersection(pr.get('perms', [])) for pr in profs):
        bad('no-work-profile', 'profiles', 'At least one ready-made profile for everyday staff, without administrator rights.')
    if profs:
        in_use = {x for pr in profs if not pr.get('locked') for x in pr.get('perms', [])}
        for x in sorted(known - admins - in_use):
            bad('perm-unused', x, 'No ready-made profile gives this permission; check it is not forgotten.', 'warning')
    return out


def errors(cat):
    return [f for f in check(cat) if f.level == 'error']


# ------------------------------------------------------------------ runtime helpers
def effective(base, extra=(), denied=()):
    """A person's permissions: profile ticks plus own extra ticks minus own removed ticks."""
    return sorted((set(base) | set(extra)) - set(denied))


def perm_diff(before, after):
    """What an administrator's save changed, for the security log."""
    b, a = set(before or ()), set(after or ())
    return {'added': sorted(a - b), 'removed': sorted(b - a)}


def matching_profile(perms, profiles):
    """The id of the profile whose ticks are exactly these, or None ("Custom")."""
    want = set(perms)
    return next((p.get('id') for p in profiles if p.get('id') and set(p.get('perms', [])) == want), None)


def admin_safety(before, after, actor_id, admin, manage='users.manage'):
    """Problems a change to people would cause. `before`/`after`: [{id, active, perms, link}] (deleted people left out of
    `after`). `admin`: the administrator permission ids. Returns a list of codes (empty = safe):

      last-manager  nobody active could manage people any more (the shop is locked out of its own settings)
      self-lockout  the person saving would remove their own right to manage people, or switch themselves off
      link-admin    somebody who signs in with a personal link would hold an administrator right
    """
    out = []
    after_by = {u['id']: u for u in after}
    if not any(u.get('active', True) and manage in u.get('perms', ()) for u in after):
        out.append('last-manager')
    me_before = next((u for u in before if u['id'] == actor_id), None)
    me_after = after_by.get(actor_id)
    if me_before and manage in me_before.get('perms', ()) and \
            (not me_after or not me_after.get('active', True) or manage not in me_after.get('perms', ())):
        out.append('self-lockout')
    if any(u.get('link') and set(admin).intersection(u.get('perms', ())) for u in after):
        out.append('link-admin')
    return out


def matrix(cat, lang='en'):
    """Markdown: one row per permission, one column per profile, ✓ where the profile gives it."""
    profs = cat.get('profiles') or []
    name = lambda x: _labels(x).get(lang) or _labels(x).get('en') or x.get('name') or x.get('id')  # noqa: E731
    rows = ['| ' + ' | '.join(['', *[name(p) for p in profs]]) + ' |', '|' + '---|' * (len(profs) + 1)]
    for g in cat.get('groups', []):
        rows.append(f'| **{name(g)}**' + ' |' * len(profs) + ' |')
        for p in g.get('permissions', []):
            rows.append('| ' + ' | '.join([name(p), *['✓' if p['id'] in pr.get('perms', []) else '' for pr in profs]]) + ' |')
    return '\n'.join(rows)


def main(argv):
    if len(argv) < 3 or argv[1] not in ('check', 'matrix'):
        print(__doc__)
        return 2
    with open(argv[2], encoding='utf-8') as f:
        cat = json.load(f)
    if argv[1] == 'matrix':
        print(matrix(cat, argv[3] if len(argv) > 3 else 'en'))
        return 0
    found = check(cat)
    for x in found:
        print(x)
    n = sum(f.level == 'error' for f in found)
    print(f'{cat.get("product", "catalogue")}: {len(all_perms(cat))} permissions, {len(cat.get("profiles") or [])} profiles, '
          f'{n} error(s), {len(found) - n} warning(s)')
    return 1 if n else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
