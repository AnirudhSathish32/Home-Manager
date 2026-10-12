"use strict";
// Global search (docs/documents.md "Searching document text"): the sidebar's search box and its shortcuts; search_v2.js
// draws the results. Ctrl+K or "/" focuses the search box; results link into each page's own filtered view.
function searchHref(query) { return `#/search?${new URLSearchParams({q: query})}`; }
// Where a document's text matched (docs/documents.md "Searching document text"). The server marks the matched words with \x02…\x03;
// they become <mark> from text nodes, never HTML, since the words come from the document.
function matchSnippet(match) {
  const quote = element("p", "", "search-snippet");
  match.snippet.split("\x02").forEach((part, index) => {
    const [marked, rest] = index ? part.split("\x03") : [null, part];
    if (marked) quote.append(element("mark", marked));
    if (rest) quote.append(document.createTextNode(rest));
  });
  return quote;
}
// A document link that opens its text at the matched lines, when the match was in the text.
function documentHref(doc) {
  return `#/documents/${doc.id}` + (doc.match ? `?${new URLSearchParams({lines: doc.match.line_ids.join(",")})}` : "");
}
$("global-search-form").addEventListener("submit", event => {
  event.preventDefault();
  const query = $("global-search").value.trim();
  if (!query) return;
  const target = searchHref(query);
  // The same hash fires no hashchange; showRoute runs Search again (search_v2.js).
  if (location.hash === target) showRoute(false); else location.hash = target;
});
document.addEventListener("keydown", event => {
  const typing = event.target.closest("input, select, textarea, [contenteditable]");
  if (((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") || (event.key === "/" && !typing && !document.querySelector("dialog[open]"))) {
    event.preventDefault();
    const box = getComputedStyle($("global-search-form")).display !== "none" ? $("global-search") : null;
    if (box) { box.focus(); box.select(); } else location.hash = "#/search";
  }
});
