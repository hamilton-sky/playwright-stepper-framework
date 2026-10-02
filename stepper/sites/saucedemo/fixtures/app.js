/*
 * A local stand-in for www.saucedemo.com — see server.py for why it exists.
 *
 * The real site is a static single-page app: every page is client-rendered,
 * the session is a `session-username` cookie and the cart is a JSON array of
 * product ids in localStorage under `cart-contents`. This reproduces that
 * state model and the DOM the POMs select on (class names and data-test
 * attributes), one HTML file per route instead of a client-side router.
 */
(function () {
  "use strict";

  var PASSWORD = "secret_sauce";
  var USERS = ["standard_user", "locked_out_user", "problem_user",
               "performance_glitch_user", "error_user", "visual_user"];

  var PRODUCTS = [
    {id: 4, name: "Sauce Labs Backpack", price: 29.99,
     desc: "carry.allTheThings() with the sleek, streamlined Sly Pack that melds uncompromising style with unequaled laptop and tablet protection."},
    {id: 0, name: "Sauce Labs Bike Light", price: 9.99,
     desc: "A red light isn't the desired state in testing but it sure helps when riding your bike at night. Water-resistant with 3 lighting modes, 1 AAA battery included."},
    {id: 1, name: "Sauce Labs Bolt T-Shirt", price: 15.99,
     desc: "Get your testing superhero on with the Sauce Labs bolt T-shirt. From American Apparel, 100% ringspun combed cotton, heather gray with red bolt."},
    {id: 5, name: "Sauce Labs Fleece Jacket", price: 49.99,
     desc: "It's not every day that you come across a midweight quarter-zip fleece jacket capable of handling everything from a relaxing day outdoors to a busy day at the office."},
    {id: 2, name: "Sauce Labs Onesie", price: 7.99,
     desc: "Rib snap infant onesie for the junior automation engineer in development. Reinforced 3-snap bottom closure, two-needle hemmed sleeved and bottom won't unravel."},
    {id: 3, name: "Test.allTheThings() T-Shirt (Red)", price: 15.99,
     desc: "This classic Sauce Labs t-shirt is perfect to wear when cozying up to your keyboard to automate a few tests. Super-soft and comfy ringspun combed cotton."}
  ];

  var SORTS = [["az", "Name (A to Z)"], ["za", "Name (Z to A)"],
               ["lohi", "Price (low to high)"], ["hilo", "Price (high to low)"]];

  var IMG = "data:image/gif;base64,R0lGODlhAQABAIAAAMLCwgAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw==";

  // ── state ───────────────────────────────────────────────────────────────────

  function user() {
    var m = document.cookie.match(/(?:^|;\s*)session-username=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }
  function setUser(name) {
    document.cookie = "session-username=" + encodeURIComponent(name) + "; path=/";
  }
  function clearUser() {
    document.cookie = "session-username=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  }
  function cart() {
    try { return JSON.parse(localStorage.getItem("cart-contents") || "[]"); }
    catch (e) { return []; }
  }
  function setCart(ids) { localStorage.setItem("cart-contents", JSON.stringify(ids)); }
  function inCart(id) { return cart().indexOf(id) !== -1; }
  function addToCart(id) { var c = cart(); if (c.indexOf(id) === -1) c.push(id); setCart(c); }
  function removeFromCart(id) { setCart(cart().filter(function (x) { return x !== id; })); }
  function product(id) { return PRODUCTS.filter(function (p) { return p.id === id; })[0]; }

  function slug(name) { return name.toLowerCase().replace(/ /g, "-"); }
  function money(n) { return "$" + n.toFixed(2); }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c];
    });
  }
  function go(path) { window.location.href = path; }

  // The real site sends an unauthenticated visitor back to the login page with
  // this banner, rather than rendering the protected page empty.
  function requireLogin(path) {
    if (user()) return true;
    sessionStorage.setItem("login-error",
      "Epic sadface: You can only access '" + path + "' when you are logged in.");
    window.location.replace("/");
    return false;
  }

  // ── shared chrome ───────────────────────────────────────────────────────────

  function header(title, extra) {
    var n = cart().length;
    return (
      '<div class="primary_header" data-test="primary-header">' +
        '<div id="menu_button_container"><div>' +
          '<div class="bm-burger-button"><button type="button" id="react-burger-menu-btn">Open Menu</button></div>' +
          '<div class="bm-menu-wrap" aria-hidden="true" hidden><div class="bm-menu"><nav class="bm-item-list">' +
            '<a id="inventory_sidebar_link" class="bm-item menu-item" href="/inventory.html" data-test="inventory-sidebar-link">All Items</a>' +
            '<a id="about_sidebar_link" class="bm-item menu-item" href="https://saucelabs.com/" data-test="about-sidebar-link">About</a>' +
            '<a id="logout_sidebar_link" class="bm-item menu-item" href="#" data-test="logout-sidebar-link">Logout</a>' +
            '<a id="reset_sidebar_link" class="bm-item menu-item" href="#" data-test="reset-sidebar-link">Reset App State</a>' +
          '</nav></div>' +
          '<div class="bm-cross-button"><button type="button" id="react-burger-cross-btn">Close Menu</button></div></div>' +
        '</div></div>' +
        '<div class="header_label"><div class="app_logo">Swag Labs</div></div>' +
        // No href: on the real site this is an <a> wired by a click handler, so
        // it has no link role. A POM reaching for it by role falls through to CSS
        // here exactly as it does there.
        '<div id="shopping_cart_container" class="shopping_cart_container">' +
          '<a class="shopping_cart_link" data-test="shopping-cart-link">' +
            (n ? '<span class="shopping_cart_badge" data-test="shopping-cart-badge">' + n + '</span>' : '') +
          '</a></div>' +
      '</div>' +
      '<div class="header_secondary_container" data-test="secondary-header">' +
        '<span class="title" data-test="title">' + esc(title) + '</span>' + (extra || '') +
      '</div>'
    );
  }

  function wireHeader(rerender) {
    var wrap = document.querySelector(".bm-menu-wrap");
    document.getElementById("react-burger-menu-btn").onclick = function () {
      wrap.hidden = false; wrap.setAttribute("aria-hidden", "false");
    };
    document.getElementById("react-burger-cross-btn").onclick = function () {
      wrap.hidden = true; wrap.setAttribute("aria-hidden", "true");
    };
    document.getElementById("logout_sidebar_link").onclick = function (e) {
      e.preventDefault(); clearUser(); go("/");
    };
    document.getElementById("reset_sidebar_link").onclick = function (e) {
      e.preventDefault(); setCart([]); if (rerender) rerender();
    };
    document.querySelector(".shopping_cart_link").onclick = function () { go("/cart.html"); };
  }

  function cartRow(p, removable) {
    return (
      '<div class="cart_item" data-test="inventory-item">' +
        '<div class="cart_quantity" data-test="item-quantity">1</div>' +
        '<div class="cart_item_label">' +
          '<a href="/inventory-item.html?id=' + p.id + '" id="item_' + p.id + '_title_link" data-test="item-' + p.id + '-title-link">' +
            '<div class="inventory_item_name" data-test="inventory-item-name">' + esc(p.name) + '</div></a>' +
          '<div class="inventory_item_desc" data-test="inventory-item-desc">' + esc(p.desc) + '</div>' +
          '<div class="item_pricebar"><div class="inventory_item_price" data-test="inventory-item-price">' + money(p.price) + '</div>' +
            (removable
              ? '<button class="btn btn_secondary btn_small cart_button" data-test="remove-' + esc(slug(p.name)) +
                '" id="remove-' + esc(slug(p.name)) + '" name="remove-' + esc(slug(p.name)) + '" data-id="' + p.id + '">Remove</button>'
              : '') +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function cartList(removable) {
    return (
      '<div class="cart_list" data-test="cart-list">' +
        '<div class="cart_quantity_label" data-test="cart-quantity-label">QTY</div>' +
        '<div class="cart_desc_label" data-test="cart-desc-label">Description</div>' +
        cart().map(product).filter(Boolean).map(function (p) { return cartRow(p, removable); }).join("") +
      '</div>'
    );
  }

  function root(html) { document.getElementById("root").innerHTML = html; }

  // ── pages ───────────────────────────────────────────────────────────────────

  function loginPage() {
    if (user()) { go("/inventory.html"); return; }

    function showError(msg) {
      var box = document.querySelector(".error-message-container");
      box.classList.add("error");
      box.innerHTML = '<h3 data-test="error"><button class="error-button" data-test="error-button" aria-label="close error"></button>' +
                      esc(msg) + '</h3>';
      document.querySelectorAll(".form_input").forEach(function (el) { el.classList.add("error"); });
    }

    var pending = sessionStorage.getItem("login-error");
    if (pending) { sessionStorage.removeItem("login-error"); showError(pending); }

    document.getElementById("login-form").onsubmit = function (e) {
      e.preventDefault();
      var name = document.getElementById("user-name").value;
      var pass = document.getElementById("password").value;
      if (!name) return showError("Epic sadface: Username is required");
      if (!pass) return showError("Epic sadface: Password is required");
      if (USERS.indexOf(name) === -1 || pass !== PASSWORD)
        return showError("Epic sadface: Username and password do not match any user in this service");
      if (name === "locked_out_user")
        return showError("Epic sadface: Sorry, this user has been locked out.");
      setUser(name);
      go("/inventory.html");
    };
  }

  function inventoryPage() {
    if (!requireLogin("/inventory.html")) return;
    var sort = "az";

    function sorted() {
      var list = PRODUCTS.slice();
      var cmp = {
        az:   function (a, b) { return a.name.localeCompare(b.name); },
        za:   function (a, b) { return b.name.localeCompare(a.name); },
        lohi: function (a, b) { return a.price - b.price; },
        hilo: function (a, b) { return b.price - a.price; }
      }[sort];
      return list.sort(cmp);
    }

    function render() {
      var label = SORTS.filter(function (s) { return s[0] === sort; })[0][1];
      var select =
        '<div class="right_component"><span class="select_container">' +
          '<span class="active_option" data-test="active-option">' + label + '</span>' +
          '<select class="product_sort_container" data-test="product-sort-container">' +
            SORTS.map(function (s) {
              return '<option value="' + s[0] + '"' + (s[0] === sort ? ' selected' : '') + '>' + s[1] + '</option>';
            }).join("") +
          '</select></span></div>';
      var items = sorted().map(function (p) {
        var s = esc(slug(p.name)), on = inCart(p.id);
        return (
          '<div class="inventory_item" data-test="inventory-item">' +
            '<div class="inventory_item_img"><a href="#" id="item_' + p.id + '_img_link" data-test="item-' + p.id + '-img-link" data-id="' + p.id + '">' +
              '<img alt="' + esc(p.name) + '" class="inventory_item_img" src="' + IMG + '"></a></div>' +
            '<div class="inventory_item_description" data-test="inventory-item-description">' +
              '<div class="inventory_item_label">' +
                '<a href="#" id="item_' + p.id + '_title_link" data-test="item-' + p.id + '-title-link" data-id="' + p.id + '">' +
                  '<div class="inventory_item_name" data-test="inventory-item-name">' + esc(p.name) + '</div></a>' +
                '<div class="inventory_item_desc" data-test="inventory-item-desc">' + esc(p.desc) + '</div>' +
              '</div>' +
              '<div class="pricebar"><div class="inventory_item_price" data-test="inventory-item-price">' + money(p.price) + '</div>' +
                (on
                  ? '<button class="btn btn_secondary btn_small btn_inventory" data-test="remove-' + s + '" id="remove-' + s + '" name="remove-' + s + '" data-id="' + p.id + '">Remove</button>'
                  : '<button class="btn btn_primary btn_small btn_inventory" data-test="add-to-cart-' + s + '" id="add-to-cart-' + s + '" name="add-to-cart-' + s + '" data-id="' + p.id + '">Add to cart</button>') +
              '</div>' +
            '</div>' +
          '</div>'
        );
      }).join("");

      root(
        '<div id="page_wrapper" class="page_wrapper"><div id="contents_wrapper">' +
          header("Products", select) +
          '<div id="inventory_container" class="inventory_container"><div>' +
            '<div class="inventory_list" data-test="inventory-list">' + items + '</div>' +
          '</div></div>' +
        '</div></div>'
      );
      wireHeader(render);

      document.querySelector(".product_sort_container").onchange = function () {
        sort = this.value; render();
      };
      document.querySelectorAll(".btn_inventory").forEach(function (b) {
        b.onclick = function () {
          var id = Number(b.getAttribute("data-id"));
          if (inCart(id)) removeFromCart(id); else addToCart(id);
          render();
        };
      });
      document.querySelectorAll(".inventory_item_label a, .inventory_item_img a").forEach(function (a) {
        a.onclick = function (e) { e.preventDefault(); go("/inventory-item.html?id=" + a.getAttribute("data-id")); };
      });
    }
    render();
  }

  function itemPage() {
    if (!requireLogin("/inventory-item.html")) return;
    var id = Number(new URLSearchParams(location.search).get("id"));
    var p = product(id);

    function render() {
      var body = p
        ? '<div class="inventory_details_container"><div class="inventory_details"><div class="inventory_details_container">' +
            '<div class="inventory_details_img_container"><img alt="' + esc(p.name) + '" class="inventory_details_img" src="' + IMG + '"></div>' +
            '<div class="inventory_details_desc_container">' +
              '<div class="inventory_details_name large_size" data-test="inventory-item-name">' + esc(p.name) + '</div>' +
              '<div class="inventory_details_desc large_size" data-test="inventory-item-desc">' + esc(p.desc) + '</div>' +
              '<div class="inventory_details_price" data-test="inventory-item-price">' + money(p.price) + '</div>' +
              (inCart(p.id)
                ? '<button class="btn btn_secondary btn_small btn_inventory" data-test="remove" id="remove" name="remove">Remove</button>'
                : '<button class="btn btn_primary btn_small btn_inventory" data-test="add-to-cart" id="add-to-cart" name="add-to-cart">Add to cart</button>') +
            '</div></div></div></div>'
        : '<div class="inventory_details_name large_size" data-test="inventory-item-name">ITEM NOT FOUND</div>';
      root(
        '<div id="page_wrapper" class="page_wrapper"><div id="contents_wrapper">' +
          header("", '<button class="btn btn_secondary back btn_large inventory_details_back_button" data-test="back-to-products" id="back-to-products" name="back-to-products">Back to products</button>') +
          body +
        '</div></div>'
      );
      wireHeader(render);
      document.getElementById("back-to-products").onclick = function () { go("/inventory.html"); };
      var btn = document.querySelector(".btn_inventory");
      if (btn) btn.onclick = function () {
        if (inCart(p.id)) removeFromCart(p.id); else addToCart(p.id);
        render();
      };
    }
    render();
  }

  function cartPage() {
    if (!requireLogin("/cart.html")) return;
    function render() {
      root(
        '<div id="page_wrapper" class="page_wrapper"><div id="contents_wrapper">' +
          header("Your Cart") +
          '<div id="cart_contents_container" class="cart_contents_container"><div>' +
            cartList(true) +
            '<div class="cart_footer">' +
              '<button class="btn btn_secondary back btn_medium" data-test="continue-shopping" id="continue-shopping" name="continue-shopping">Continue Shopping</button>' +
              '<button class="btn btn_action btn_medium checkout_button" data-test="checkout" id="checkout" name="checkout">Checkout</button>' +
            '</div>' +
          '</div></div>' +
        '</div></div>'
      );
      wireHeader(render);
      document.getElementById("continue-shopping").onclick = function () { go("/inventory.html"); };
      document.getElementById("checkout").onclick = function () { go("/checkout-step-one.html"); };
      document.querySelectorAll(".cart_button").forEach(function (b) {
        b.onclick = function () { removeFromCart(Number(b.getAttribute("data-id"))); render(); };
      });
    }
    render();
  }

  function checkoutStepOne() {
    if (!requireLogin("/checkout-step-one.html")) return;
    function field(testId, id, placeholder) {
      return '<div class="form_group"><input class="input_error form_input" placeholder="' + placeholder +
             '" type="text" data-test="' + testId + '" id="' + id + '" name="' + testId + '" autocorrect="off" autocapitalize="none" value=""></div>';
    }
    root(
      '<div id="page_wrapper" class="page_wrapper"><div id="contents_wrapper">' +
        header("Checkout: Your Information") +
        '<div id="checkout_info_container" class="checkout_info_container"><div class="checkout_info_wrapper">' +
          '<form id="checkout-form"><div class="checkout_info">' +
            field("firstName", "first-name", "First Name") +
            field("lastName", "last-name", "Last Name") +
            field("postalCode", "postal-code", "Zip/Postal Code") +
            '<div class="error-message-container"></div>' +
          '</div>' +
          '<div class="checkout_buttons">' +
            '<button type="button" class="btn btn_secondary back btn_medium cart_cancel_link" data-test="cancel" id="cancel" name="cancel">Cancel</button>' +
            '<input type="submit" class="submit-button btn btn_primary cart_button btn_action" data-test="continue" id="continue" name="continue" value="Continue">' +
          '</div></form>' +
        '</div></div>' +
      '</div></div>'
    );
    wireHeader();
    document.getElementById("cancel").onclick = function () { go("/cart.html"); };
    document.getElementById("checkout-form").onsubmit = function (e) {
      e.preventDefault();
      var checks = [["first-name", "First Name"], ["last-name", "Last Name"], ["postal-code", "Postal Code"]];
      for (var i = 0; i < checks.length; i++) {
        if (!document.getElementById(checks[i][0]).value) {
          var box = document.querySelector(".error-message-container");
          box.classList.add("error");
          box.innerHTML = '<h3 data-test="error"><button class="error-button" data-test="error-button" aria-label="close error"></button>Error: ' +
                          checks[i][1] + ' is required</h3>';
          return;
        }
      }
      go("/checkout-step-two.html");
    };
  }

  function checkoutStepTwo() {
    if (!requireLogin("/checkout-step-two.html")) return;
    var items = cart().map(product).filter(Boolean);
    var subtotal = items.reduce(function (s, p) { return s + p.price; }, 0);
    var tax = Math.round(subtotal * 0.08 * 100) / 100;
    root(
      '<div id="page_wrapper" class="page_wrapper"><div id="contents_wrapper">' +
        header("Checkout: Overview") +
        '<div id="checkout_summary_container" class="checkout_summary_container"><div>' +
          cartList(false) +
          '<div class="summary_info">' +
            '<div class="summary_info_label" data-test="payment-info-label">Payment Information:</div>' +
            '<div class="summary_value_label" data-test="payment-info-value">SauceCard #31337</div>' +
            '<div class="summary_info_label" data-test="shipping-info-label">Shipping Information:</div>' +
            '<div class="summary_value_label" data-test="shipping-info-value">Free Pony Express Delivery!</div>' +
            '<div class="summary_info_label" data-test="total-info-label">Price Total</div>' +
            '<div class="summary_subtotal_label" data-test="subtotal-label">Item total: ' + money(subtotal) + '</div>' +
            '<div class="summary_tax_label" data-test="tax-label">Tax: ' + money(tax) + '</div>' +
            '<div class="summary_info_label summary_total_label" data-test="total-label">Total: ' + money(subtotal + tax) + '</div>' +
            '<div class="cart_footer">' +
              '<button class="btn btn_secondary back btn_medium cart_cancel_link" data-test="cancel" id="cancel" name="cancel">Cancel</button>' +
              '<button class="btn btn_action btn_medium cart_button" data-test="finish" id="finish" name="finish">Finish</button>' +
            '</div>' +
          '</div>' +
        '</div></div>' +
      '</div></div>'
    );
    wireHeader();
    document.getElementById("cancel").onclick = function () { go("/inventory.html"); };
    document.getElementById("finish").onclick = function () { setCart([]); go("/checkout-complete.html"); };
  }

  function checkoutComplete() {
    if (!requireLogin("/checkout-complete.html")) return;
    root(
      '<div id="page_wrapper" class="page_wrapper"><div id="contents_wrapper">' +
        header("Checkout: Complete!") +
        '<div id="checkout_complete_container" class="checkout_complete_container" data-test="checkout-complete-container">' +
          '<img alt="Pony Express" class="pony_express" data-test="pony-express" src="' + IMG + '">' +
          '<h2 class="complete-header" data-test="complete-header">Thank you for your order!</h2>' +
          '<div class="complete-text" data-test="complete-text">Your order has been dispatched, and will arrive just as fast as the pony can get there!</div>' +
          '<button class="btn btn_primary btn_small" data-test="back-to-products" id="back-to-products" name="back-to-products">Back Home</button>' +
        '</div>' +
      '</div></div>'
    );
    wireHeader();
    document.getElementById("back-to-products").onclick = function () { go("/inventory.html"); };
  }

  window.SD = {
    loginPage: loginPage, inventoryPage: inventoryPage, itemPage: itemPage,
    cartPage: cartPage, checkoutStepOne: checkoutStepOne,
    checkoutStepTwo: checkoutStepTwo, checkoutComplete: checkoutComplete
  };
})();
