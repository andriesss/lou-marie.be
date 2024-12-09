const fs = require("fs");
const path = require("path");
const { minify } = require("terser");
const sharp = require("sharp");

function readFilesRecursively(dir) {
    let results = [];
    const list = fs.readdirSync(dir);
    list.forEach(file => {
        file = path.resolve(dir, file);
        const stat = fs.statSync(file);
        if (stat && stat.isDirectory()) {
            results = results.concat(readFilesRecursively(file));
        } else {
            results.push(file);
        }
    });

    return results;
}

module.exports = function (eleventyConfig) {
    eleventyConfig.addPassthroughCopy("css");
    eleventyConfig.addPassthroughCopy("browserconfig.xml");
    eleventyConfig.addPassthroughCopy("site.webmanifest");
    eleventyConfig.addPassthroughCopy("src/robots.txt");
    eleventyConfig.addPassthroughCopy("js");
    eleventyConfig.addPassthroughCopy("images");

    let _CAPTURES;
    eleventyConfig.on('beforeBuild', async () => {
        //I need this to wipe _CAPTURES when editing pages, wouldn't be an issue in prod
        _CAPTURES = {};

        eleventyConfig.addPassthroughCopy("js");
        eleventyConfig.addPassthroughCopy("images");

        if (process.env.ELEVENTY_RUN_MODE !== "serve") {
            const srcDir = "./js";
            const outputDir = "./dist/js";

            if (!fs.existsSync(outputDir)) {
                fs.mkdirSync(outputDir, {recursive: true});
            }

            const files = fs.readdirSync(srcDir);
            for (const file of files) {
                if (path.extname(file) === ".js") {
                    const filePath = path.join(srcDir, file);
                    const content = fs.readFileSync(filePath, "utf-8");
                    const minified = await minify(content);
                    fs.writeFileSync(path.join(outputDir, file), minified.code);
                }
            }
        }

        if (process.env.ELEVENTY_RUN_MODE !== "serve") {
            const imageSrcDir = "./images";
            const imageOutputDir = "./dist/images";

            if (!fs.existsSync(imageOutputDir)) {
                fs.mkdirSync(imageOutputDir, {recursive: true});
            }

            const imageFiles = readFilesRecursively(imageSrcDir);
            for (const imageFile of imageFiles) {
                const ext = path.extname(imageFile).toLowerCase();
                const outputImagePath = path.join(imageOutputDir, path.relative(imageSrcDir, imageFile));
                const outputImageDir = path.dirname(outputImagePath);
                if (!fs.existsSync(outputImageDir)) {
                    fs.mkdirSync(outputImageDir, {recursive: true});
                }

                fs.copyFileSync(imageFile, outputImagePath);

                if (ext === ".jpg" || ext === ".jpeg" || ext === ".png") {
                    const webpImagePath = outputImagePath.replace(ext, ".webp");
                    await sharp(imageFile).webp().toFile(webpImagePath);
                }
            }
        }
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
            currencyDisplay: 'name'
        }).format(value);
    });

    const sizeMap = {
        S: 'S (36/38)',
        M: 'M (38/40)',
        L: 'L (40/42)',
        XL: 'XL (42/44)',
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


    eleventyConfig.addShortcode("picture", function(image, title) {
        if (process.env.ELEVENTY_RUN_MODE === "serve") {
            return `<picture><img src="${image}" alt="${title}" class="product-image img-fluid"></picture>`;
        } else {
            return `<picture>
            <source srcset="${image.replace('.jpg', '.webp')}" type="image/webp">
            <img src="${image}" alt="${title}" class="product-image img-fluid">
          </picture>`;
        }
    });

    return {
        dir: {
            input: "src",
            output: "dist",
        }
    }
}