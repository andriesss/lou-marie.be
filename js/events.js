let queue = []
let gTagQueue = []
let hasTrackerLoaded = false
let hasCookieConsent = false

function sendFBQEvent(command, category, payload, customData = {}) {
    console.info("Sending FBQ event", new Date(), command, category, payload, customData);
    window.fbq(command, category, payload, customData);
}

function sendGTagEvent(command, category, payload) {
    console.info("Sending Gtag event", new Date(), command, category, payload);
    gtag(command, category, payload);
}

function trackEvent(command, category, payload, customData) {
    if (!hasTrackerLoaded || !hasCookieConsent || !window.fbq) {
        if (command === 'consent') {
            queue.unshift({command, category, payload});
        } else {
            queue.push({command, category, payload, customData});
        }
        return
    }

    sendFBQEvent(command, category, payload, customData)
}

function trackGTagEvent(command, category, payload) {
    if (!hasCookieConsent) {
        gTagQueue.push({command, category, payload});
        return
    }

    sendGTagEvent(command, category, payload)
}

function onAddToCart(id, title, price) {
    trackEvent('track', 'AddToCart', {
        content_ids: [id],
        content_type: 'product'
    });

    trackEvent('track', 'InitiateCheckout', {
        content_ids: [id],
    });


    trackGTagEvent("event", "add_to_cart", {
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

    trackGTagEvent("event", "begin_checkout", {
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
    hasTrackerLoaded = true;
    function processQueue() {
        if (queue.length) {
            const {command, category, payload, customData} = queue.shift();
            sendFBQEvent(command, category, payload, customData);
            setTimeout(processQueue, 0);
        }
    }
    processQueue();
}

function handleConsent(hasConsent) {
    hasCookieConsent = hasConsent;
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

    function processGTagQueue() {
        if (gTagQueue.length) {
            const {command, category, payload} = gTagQueue.shift();
            sendGTagEvent(command, category, payload);
            setTimeout(processGTagQueue, 0);
        }
    }
    processGTagQueue();
}

window.addEventListener("cookie_consent", (eventData) => {
    const data = eventData.detail
    handleConsent(data.accepted);
});
