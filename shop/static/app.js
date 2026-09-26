// Konfirmasi sebelum submit, dipasang lewat atribut data-confirm.
// Dipisah dari HTML supaya CSP bisa melarang script inline.
document.addEventListener(
  "submit",
  function (event) {
    var form = event.target;
    if (!form || !form.getAttribute) return;
    var message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  },
  true
);
