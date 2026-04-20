(function(){
  try {
    if (window.__HA_CLAUDE_BUBBLE_LOADER__) return;
    window.__HA_CLAUDE_BUBBLE_LOADER__ = true;
    var parts = [
      '/local/ha-claude-chat-bubble.bubble.js?v=4.7.3&h=bd85e3dd',
      '/local/ha-claude-chat-bubble.card.js?v=4.7.3&h=14f0833d',
      '/local/ha-claude-chat-bubble.automation.js?v=4.7.3&h=0f00b88a'
    ];
    function loadOne(src) {
      return new Promise(function(resolve) {
        var s = document.createElement('script');
        s.src = src;
        s.async = false;
        s.dataset.amiraPart = src;
        s.onload = function() { resolve(); };
        s.onerror = function() { resolve(); };
        (document.head || document.documentElement || document.body).appendChild(s);
      });
    }
    (async function() {
      for (var i = 0; i < parts.length; i++) await loadOne(parts[i]);
    })();
  } catch (e) {
    console.error('[Amira loader] error:', e);
  }
})();
