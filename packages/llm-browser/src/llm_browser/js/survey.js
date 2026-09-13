// What the page offers an author before any selector is written: the elements
// that carry a name, the links that share a shape, the structures that repeat,
// and how long the page has been up. Reads only — never clicks, never scrolls.
//
// Raw material, not the answer: which landmark outranks which, what a link
// shape is called and which repeats are the same card live in
// `llm_browser.survey`, so they can be tested without a browser.
(el) => {
  const limits = SURVEY_LIMITS_JSON;
  const doc = el.ownerDocument;
  const squeeze = (value, max) =>
    String(value || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, max);
  const classesOf = (node) => Array.from(node.classList);

  const testidOf = (node) => {
    for (const attribute of limits.testid_attributes) {
      const value = node.getAttribute(attribute);
      if (value) return { testid_attribute: attribute, testid: value };
    }
    return { testid_attribute: null, testid: null };
  };

  const landmarks = [];
  for (const node of doc.querySelectorAll("*")) {
    if (landmarks.length >= limits.max_raw_landmarks) break;
    const { testid_attribute, testid } = testidOf(node);
    const aria_label = node.getAttribute("aria-label");
    const id = node.getAttribute("id");
    const role = node.getAttribute("role");
    if (!testid && !aria_label && !id && !role) continue;
    landmarks.push({
      tag: node.tagName.toLowerCase(),
      testid_attribute,
      testid,
      aria_label,
      id,
      role,
      text: squeeze(node.innerText || node.textContent, limits.text_max),
    });
  }

  const hrefs = Array.from(doc.querySelectorAll("a[href]"))
    .slice(0, limits.max_hrefs)
    .map((anchor) => anchor.getAttribute("href"));

  // A repeat is a run of siblings of the same tag: the cards, rows and list
  // items a page is built of. Their classes come along so the caller can tell
  // one component's cards from the next one's.
  const repeats = [];
  for (const parent of doc.querySelectorAll("*")) {
    if (repeats.length >= limits.max_raw_repeats) break;
    const children = Array.from(parent.children);
    if (children.length < limits.min_siblings) continue;
    const byTag = new Map();
    for (const child of children) {
      const tag = child.tagName.toLowerCase();
      if (!byTag.has(tag)) byTag.set(tag, []);
      byTag.get(tag).push(child);
    }
    const parentTestid = testidOf(parent);
    for (const [tag, members] of byTag) {
      if (members.length < limits.min_siblings) continue;
      const shared = classesOf(members[0]).filter((token) =>
        members.every((member) => member.classList.contains(token)),
      );
      repeats.push({
        tag,
        count: members.length,
        classes: classesOf(members[0]),
        shared_classes: shared,
        parent: {
          tag: parent.tagName.toLowerCase(),
          testid_attribute: parentTestid.testid_attribute,
          testid: parentTestid.testid,
          id: parent.getAttribute("id"),
        },
        nested_controls: Array.from(
          members[0].querySelectorAll("button, a, input"),
        )
          .slice(0, limits.max_nested_controls)
          .map((control) => ({
            tag: control.tagName.toLowerCase(),
            text: squeeze(
              control.innerText || control.value || control.textContent,
              limits.nested_text_max,
            ),
          })),
      });
    }
  }

  return {
    title: squeeze(doc.title, limits.text_max),
    url: doc.location.href,
    ready_state: doc.readyState,
    since_navigation_ms: Math.round(performance.now()),
    landmarks,
    hrefs,
    repeats,
  };
}
