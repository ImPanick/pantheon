// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/pdfFontCoverage.js
//
// `B1687`. Written by `node scripts/build-pdf-font-coverage.mjs`; not edited
// by hand. The characters each face the fallback PDF embeds draws, read out
// of the vendored file by the vendored jsPDF (`characterToGlyph` over the
// cmap it parses, the question `document.js` asks once the face is loaded),
// as hexadecimal code points and `first-last` ranges. `_pdfFontsNeeded`
// reads it to decide, before anything is fetched, whether a document needs
// the face at all.
//
// Inter-Regular.ttf: sha256 40d692fce188e4471e2b3cba937be967878f631ad3ebbbdcd587687c7ebe0c82, 203 ranges.
export const PDF_FONT_COVERAGE = {
  "Inter-Regular.ttf": [
    "0", "20-7e", "a0-ac", "ae-148", "14a-1c3", "1c5-254", "256-27b", "27e-284", "286-290", "292-2a4",
    "2a6-304", "306-30a", "30c", "30f", "313", "315", "31b", "323", "326-328", "32c",
    "337-338", "342-343", "346-36f", "374-376", "37a-37f", "384-38a", "38c", "38e-3a1", "3a3-3d7", "3dc-3dd",
    "3f0-3f6", "3f9-3fa", "3fc-479", "480-49d", "4a0-4ff", "52f", "e3f", "1d00", "1d0d", "1d1b",
    "1d43", "1d47-1d49", "1d4d", "1d4f-1d50", "1d52", "1d56-1d58", "1d5b", "1d62-1d65", "1d9c", "1da0",
    "1dbb", "1dbf-1df5", "1dfc-1e9b", "1e9d-1f15", "1f18-1f1d", "1f20-1f45", "1f48-1f4d", "1f50-1f57", "1f59", "1f5b",
    "1f5d", "1f5f-1f7d", "1f80-1fb4", "1fb6-1fc4", "1fc6-1fd3", "1fd6-1fdb", "1fdd-1fef", "1ff2-1ff4", "1ff6-1ffe", "2000-200b",
    "2010-2027", "202f-2055", "2057", "205f", "2070-2071", "2074-208e", "2090-209c", "20a0-20af", "20b1-20b5", "20b8-20ba",
    "20bc-20c0", "20db-20de", "20e8", "20f0", "2100-2101", "2103", "2105-2106", "2109", "2113", "2116-2117",
    "211e-2122", "2126", "212a-212b", "212e", "2132", "213b", "214d", "2150-217f", "2183-2186", "2189",
    "2190-2199", "21a9-21aa", "21b0-21b1", "21b3-21b5", "21ba-21bb", "21d0", "21d2", "21d4", "21de-21df", "21e4-21e5",
    "21e7", "21ea", "2202", "2205-2206", "220f", "2211-2212", "221a", "221e", "222b", "2236",
    "2248", "2260", "2264-2265", "2295-2298", "2303-2305", "2318", "2325-2327", "232b", "2380", "2387",
    "238b", "23ce-23cf", "2423", "2460-2468", "24b6-24cf", "24ea", "25a0-25a2", "25aa", "25b2-25b3", "25b6-25b7",
    "25ba-25bd", "25c0-25c1", "25c4-25c7", "25ca-25cb", "25cf", "25e6", "25ef", "2600", "2605-2606", "263c",
    "2661", "2665", "266a-266b", "26a0", "2713", "2717", "2756", "2764", "2780-2788", "27ef",
    "27f5-27fa", "2913", "2a38", "2b06", "2b12-2b13", "2b1c", "2b24", "2c7c", "2c7f", "2dff",
    "2e18", "a69f", "a7ff", "a92e", "e000", "e002-e05e", "e06a-e0bd", "e0c8-e0cc", "e0dc-e0e6", "e0f3-e0f5",
    "e106", "e109-e10a", "e10c-e10f", "e111-e113", "e117-e118", "e121-e122", "e124", "e12a-e15e", "e163", "e1c3",
    "e1d2-e1df", "e1e1-e2dc", "ee01-ee07", "ee09-ee0a", "ee0c-ee12", "ee14", "ee17", "ee1d-ee45", "ee47-ee84", "ee87-eed6",
    "eed8-eee1", "f6c3", "feff"
  ]
};
