// frontend/js/views/keywords.js
const INPUT_ID = 'keywordInput';
const CONTAINER_ID = 'keywordTags';
const FEEDBACK_ID = 'keywordFeedback';
const CONTROL_CHARACTERS = /[\x00-\x1f\x7f-\x9f]/u;

// Module-private state
let _keywords = [];

export function initKeywords() {
  _keywords = [];

  const container = document.getElementById(CONTAINER_ID);
  if (container) {
    container.removeEventListener('click', _handleRemoveClick);
    container.addEventListener('click', _handleRemoveClick);
  }
  const input = document.getElementById(INPUT_ID);
  input?.removeEventListener('keydown', _handleKeywordKeydown);
  input?.addEventListener('keydown', _handleKeywordKeydown);
  _setFeedback('');
}

function _handleKeywordKeydown(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    addKeyword();
  }
}

function _handleRemoveClick(event) {
  const button = event.target.closest('[data-keyword-index]');
  if (button && !button.disabled) {
    removeKeyword(Number(button.dataset.keywordIndex));
  }
}

function _setFeedback(message, invalid = false) {
  const feedback = document.getElementById(FEEDBACK_ID);
  const input = document.getElementById(INPUT_ID);
  if (feedback) {
    feedback.textContent = message;
    feedback.classList.toggle('text-danger', invalid);
    feedback.classList.toggle('text-success', !invalid && Boolean(message));
  }
  if (input) input.setAttribute('aria-invalid', String(invalid));
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
  if (!input || input.disabled) return;
  const keyword = input.value.trim();

  let error = '';
  if (!keyword) error = 'Enter a keyword before adding it.';
  else if (Array.from(keyword).length > 50) error = 'Keywords must be 50 characters or fewer.';
  else if (CONTROL_CHARACTERS.test(keyword)) error = 'Keywords cannot contain control characters.';
  else if (_keywords.some(existing => existing.trim().toLocaleLowerCase('en-US') === keyword.toLocaleLowerCase('en-US'))) {
    error = 'This keyword has already been added.';
  }

  if (error) {
    _setFeedback(error, true);
    input.focus();
    return;
  }

  _keywords.push(keyword);
  displayKeywords();
  input.value = '';
  _setFeedback('Keyword added.');
  input.focus();
}

export function removeKeyword(index) {
  const input = document.getElementById(INPUT_ID);
  if (!input || input.disabled || index < 0 || index >= _keywords.length) return;
  _keywords.splice(index, 1);
  displayKeywords();
  _setFeedback('Keyword removed.');
  const buttons = document.querySelectorAll(`#${CONTAINER_ID} [data-keyword-index]`);
  (buttons[Math.min(index, buttons.length - 1)] || input).focus();
}

export function setKeywordsLocked(locked) {
  displayKeywords(locked);
}

export function displayKeywords(locked = document.getElementById(INPUT_ID)?.disabled) {
  const container = document.getElementById(CONTAINER_ID);
  if (!container) return;

  container.replaceChildren();
  _keywords.forEach((keyword, index) => {
    const tag = document.createElement('span');
    tag.className = 'badge bg-light text-dark me-2 mb-2';
    tag.setAttribute('role', 'listitem');
    tag.append(document.createTextNode(keyword));
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-link p-0 ms-1 text-dark';
    button.dataset.keywordIndex = index;
    button.setAttribute('aria-label', `Remove keyword ${keyword} (${index + 1})`);
    button.disabled = locked;
    const icon = document.createElement('i');
    icon.className = 'fas fa-times';
    icon.setAttribute('aria-hidden', 'true');
    button.append(icon);
    tag.append(button);
    container.append(tag);
  });
}
