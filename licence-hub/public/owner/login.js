'use strict';
if (location.search.indexOf('bad=1') >= 0) {
  const el = document.getElementById('bad');
  if (el) el.hidden = false;
}
