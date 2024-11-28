let queue = []
let hasTrackerLoaded = false
let hasConsent = false

function sendFBQEvent(command, category, payload) {
    window.fbq(command, category, payload);
}

function trackEvent(category, payload) {
    if (!hasTrackerLoaded || !hasConsent || !window.fbq) {
        queue.push({category, payload})
        return
    }

    sendFBQEvent(category, payload)
}

function onAddToCart(id, title, price) {
    trackEvent('track', 'AddToCart', {
        content_ids: [id],
    });

    trackEvent('track', 'InitiateCheckout', {
        content_ids: [id],
    });

    gtag("event", "begin_checkout", {
        currency: "EUR",
        value: price,
        items: [
            {
                item_id: id,
                item_name: title,
                price: price,
                quantity: 1,
            }
        ]
    });
}

function trackerLoaded() {
    trackerLoaded = true;
    while (queue.length) {
        const {category, payload} = queue.shift()
        sendFBQEvent(category, payload)
    }
}

function handleConsent(hasConsent) {
    if (!hasConsent) {
        return;
    }

    console.info("Consent granted");
    trackEvent("consent", hasConsent ? "grant" : "revoke");

    gtag('consent', 'update', {
        'ad_user_data': 'denied',
        'ad_personalization': 'denied',
        'ad_storage': 'denied',
        'analytics_storage': 'granted'
    });
}

window.addEventListener("cookie_consent", (eventData) => {
    const data = eventData.detail
    handleConsent(data.accepted);
});
