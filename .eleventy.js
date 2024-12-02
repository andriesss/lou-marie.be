module.exports = function (eleventyConfig) {
    eleventyConfig.addPassthroughCopy("images");
    eleventyConfig.addPassthroughCopy("js");
    eleventyConfig.addPassthroughCopy("css");
    eleventyConfig.addPassthroughCopy("browserconfig.xml");
    eleventyConfig.addPassthroughCopy("site.webmanifest");
    eleventyConfig.addPassthroughCopy("src/robots.txt");

    let _CAPTURES;
    eleventyConfig.on('beforeBuild', () => {
        //I need this to wipe _CAPTURES when editing pages, wouldn't be an issue in prod
        _CAPTURES = {};
    });


    eleventyConfig.addPairedShortcode("mycapture", function (content, name) {
        if(!_CAPTURES[this.page.inputPath]) _CAPTURES[this.page.inputPath] = {};
        if(!_CAPTURES[this.page.inputPath][name]) _CAPTURES[this.page.inputPath][name] = '';
        _CAPTURES[this.page.inputPath][name] += content;
        return '';
    });

    eleventyConfig.addShortcode("displaycapture", function(name) {
        if(_CAPTURES[this.page.inputPath] && _CAPTURES[this.page.inputPath][name]) return _CAPTURES[this.page.inputPath][name];
        return '';
    });

    eleventyConfig.addFilter("currency", function(value) {
        return new Intl.NumberFormat('nl-NL', {
            style: 'currency',
            currency: 'EUR',
            currencyDisplay: 'code'
        }).format(value);
    });

    const sizeMap = {
        S: 'S (36/38)',
        M: 'M (38/40)',
        L: 'L (40/42)',
        XL: 'L (42/44)',
        OSFA: 'Taille unique',
    };

    eleventyConfig.addFilter("product_size", function(value) {
        return sizeMap[value] || value;
    });

    eleventyConfig.addFilter("material", function(value) {
        return value.map(item => item.replace(/(.+)(:.+)/g, '$1').toLowerCase()).join('/');
    });

    eleventyConfig.addFilter("randomOrder", (arr) => {
        return arr.sort(() => {
            return 0.5 - Math.random();
        });
    });

    eleventyConfig.addFilter("fullSlug", (inputPath) => {
        return inputPath.split('/').pop().replace(/\.[^/.]+$/, ""); // Remove extension
    });

    eleventyConfig.addFilter("shuffle", (array) => {
        let shuffled = array.slice(); // Create a shallow copy to avoid mutating the original array
        for (let i = shuffled.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
        }
        return shuffled;
    });


    eleventyConfig.addCollection("productJson", function(collectionApi) {
        return collectionApi.getFilteredByGlob("src/kleding/*.html").map(item => {
            return {
                productId: item.data.id,
                title: item.data.title,
                price: item.data.price
            };
        });
    });

    return {
        dir: {
            input: "src",
            output: "dist",
        }
    }
}