function trackEvent(category, payload, retries = 3) {
    if (localStorage.getItem("GlowCookies") !== "1") {
        return;
    }

    try {
        window.fbq('track', category, payload);
    } catch (err) {
        if (retries > 0) {
            setTimeout(function () {
                trackEvent(category, payload, retries - 1);
                },
                500
            );
        }
    }
}

function onAddToCart(id) {
    trackEvent('AddToCart', {
        content_ids: [id],
    });
}
