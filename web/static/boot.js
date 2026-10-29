/* CINEBOX boot */
document.addEventListener('DOMContentLoaded', () => {
  if (window.CB && typeof window.CB.boot === 'function') window.CB.boot();
});
