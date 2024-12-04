let queue = []
let gtagQueue = []
let hasFBQTrackerLoaded = false
let hasCookieConsent = false

function sendFBQEvent(command, category, payload, customData = {}) {
    console.info("Sending FBQ event", command, category, payload, customData);
    window.fbq(command, category, payload, customData);
}

function sendGTagEvent(command, category, payload) {
    console.info("Sending gtag event", command, category, payload);
    gtag(command, category, payload);
}

function trackEvent(command, category, payload, customData) {
    if (!hasFBQTrackerLoaded || !hasCookieConsent || !window.fbq) {
        if (command === 'consent') {
            queue.unshift({command, category, payload});
        } else {
            queue.push({command, category, payload, customData});
        }
        return
    }

    sendFBQEvent(command, category, payload)
}

function trackGtagEvent(command, category, payload) {
    if (!hasCookieConsent || !window.gtag) {
        gtagQueue.push({command, category, payload});
    }

    sendGTagEvent(command, category, payload)
}

function onAddToCart(id, title, price) {
    trackEvent('track', 'AddToCart', {
        content_ids: [id],
    });

    trackEvent('track', 'InitiateCheckout', {
        content_ids: [id],
    });

    trackGtagEvent("event", "begin_checkout", {
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
    hasFBQTrackerLoaded = true;
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
    console.log("handle consent");
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

    function processQueue() {
        if (gtagQueue.length) {
            const {command, category, payload} = gtagQueue.shift();
            sendGTagEvent(command, category, payload);
            setTimeout(processQueue, 0);
        }
    }

    processQueue();
}

window.addEventListener("cookie_consent", (eventData) => {
    const data = eventData.detail
    handleConsent(data.accepted);
});
