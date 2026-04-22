// frontend/js/views/keywords.js
import { escapeHtml } from '../utils.js';

const INPUT_ID = 'keywordInput';
const CONTAINER_ID = 'keywordTags';

// Module-private state
let _keywords = [];

export function initKeywords() {
  _keywords = [];

  // Delegated listener: handle remove clicks via data-keyword-index attribute
  const container = document.getElementById(CONTAINER_ID);
  if (container) {
    container.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-keyword-index]');
      if (btn) {
        removeKeyword(Number(btn.dataset.keywordIndex));
      }
    });
  }
}

export function getKeywords() {
  return [..._keywords];
}

export function setKeywords(arr) {
  _keywords = Array.isArray(arr) ? [...arr] : [];
  displayKeywords();
}

export function addKeyword() {
  const input = document.getElementById(INPUT_ID);
  const keyword = input.value.trim();

  if (keyword && !_keywords.includes(keyword)) {
    _keywords.push(keyword);
    displayKeywords();
    input.value = '';
  }
}

export function removeKeyword(index) {
  _keywords.splice(index, 1);
  displayKeywords();
}

export function displayKeywords() {
  const container = document.getElementById(CONTAINER_ID);
  if (!container) return;

  container.innerHTML = _keywords
    .map(
      (kw, idx) => `
        <span class="badge bg-light text-dark me-2 mb-2">
          ${escapeHtml(kw)}
          <span data-keyword-index="${idx}" style="cursor: pointer; margin-left: 0.5rem;" aria-label="Remove ${escapeHtml(kw)}">x</span>
        </span>`
    )
    .join('');
}
