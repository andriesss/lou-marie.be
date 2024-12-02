let queue = []
let hasTrackerLoaded = false
let hasConsentForFbq = false

function sendFBQEvent(command, category, payload, customData = {}) {
    console.info("Sending FBQ event", command, category, payload, customData);
    window.fbq(command, category, payload, customData);
}

function trackEvent(command, category, payload) {
    if (!hasTrackerLoaded || !hasConsentForFbq || !window.fbq) {
        if (command === 'consent') {
            queue.unshift({command, category, payload});
        } else {
            queue.push({command, category, payload});
        }
        return
    }

    sendFBQEvent(command, category, payload)
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
    hasTrackerLoaded = true;
    function processQueue() {
        if (queue.length) {
            const {command, category, payload} = queue.shift();
            sendFBQEvent(command, category, payload);
            setTimeout(processQueue, 0);
        }
    }
    processQueue();
}

function handleConsent(hasConsent) {
    hasConsentForFbq = hasConsent;
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
