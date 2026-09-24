/* Keeps an open console page in step with the live session.

   Asks /live/status.json every few seconds. The Live Demo page's session
   controls are updated in place; the page itself reloads only when what it
   shows has changed, and never while someone is typing in a field or
   choosing from a list. Everything still works without this file: every
   control is a plain form.
*/
(function () {
  "use strict";
  var body = document.body;
  var url = body.getAttribute("data-live-url");
  if (!url) {
    return;
  }
  var every = Number(body.getAttribute("data-live-every")) || 2000;
  var stamp = body.getAttribute("data-live-stamp");

  function busy() {
    var active = document.activeElement;
    if (!active) {
      return false;
    }
    var tag = active.tagName;
    return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
  }

  function setText(name, text) {
    var node = document.querySelector('[data-live="' + name + '"]');
    if (node && typeof text === "string") {
      node.textContent = text;
    }
  }

  function tick() {
    fetch(url, { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        setText("line", data.line);
        setText("surge", data.surge_line);
        setText("reason", data.attack_reason);
        var attack = document.querySelector('[data-live="attack"]');
        if (attack) {
          // Held off while the guided demo runs: it attacks by itself.
          attack.disabled = !data.can_attack || attack.hasAttribute("data-live-hold");
        }
        if (data.stamp !== stamp && !busy()) {
          window.location.reload();
          return;
        }
        window.setTimeout(tick, every);
      })
      .catch(function () {
        window.setTimeout(tick, every);
      });
  }

  window.setTimeout(tick, every);
})();
