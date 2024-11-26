module.exports = function (eleventyConfig) {
    eleventyConfig.addPassthroughCopy("images");
    eleventyConfig.addPassthroughCopy("js");
    eleventyConfig.addPassthroughCopy("css");
    eleventyConfig.addPassthroughCopy("browserconfig.xml");
    eleventyConfig.addPassthroughCopy("site.webmanifest");

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
        OSFA: 'Taille unique',
    };

    eleventyConfig.addFilter("product_size", function(value) {
        return sizeMap[value] || value;
    });

    eleventyConfig.addFilter("material", function(value) {
        return value.map(item => item.replace(/(.+)(:.+)/g, '$1').toLowerCase()).join('/');
    });

    return {
        dir: {
            input: "src",
            output: "dist",
        }
    }
}