let queue = []
let isLoaded = false

function sendEvent (category, payload) {
    window.fbq('track', category, payload);
}

function trackerLoaded() {
    isLoaded = true
    while (queue.length) {
        const { category, payload } = queue.shift()
        sendEvent(category, payload)
    }
}

function trackEvent(category, payload) {
    if (!window.fbq || !isLoaded) {
        queue.push({ category, payload })
        return
    }
    sendEvent(category, payload)
}

function onAddToCart(id) {
    trackEvent('AddToCart', {
        content_ids: [id],
    });
}
