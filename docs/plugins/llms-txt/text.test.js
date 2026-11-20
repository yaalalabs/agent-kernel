// Run with `npm test` in docs/ (Node's built-in test runner, no dependency).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { oneSentence, outsideCode, bodyOf, openingOf, rewriteLinks } = require('./text');

const FENCE3 = '```';
const FENCE4 = '````';

test('oneSentence keeps the first sentence, on one line, without emphasis marks', () => {
  assert.equal(oneSentence('**Tools** let agents act.\nThey can also read `data`.'), 'Tools let agents act.');
  assert.equal(oneSentence('Runs on v0.10.1 and later. More.'), 'Runs on v0.10.1 and later.');
  assert.equal(oneSentence('Use e.g. Redis. Then more.'), 'Use e.g. Redis.');
  assert.equal(oneSentence('Set min_instance_count to 1.'), 'Set min_instance_count to 1.');
  assert.equal(oneSentence('See the [quick start](./quick-start.md) first.'), 'See the quick start first.');
  assert.equal(oneSentence(''), '');
  assert.equal(oneSentence(undefined), '');
});

test('oneSentence ends an opening that leads into a list or breaks off', () => {
  assert.equal(oneSentence('There are two kinds of memory:'), 'There are two kinds of memory.');
  assert.equal(
    oneSentence('Queue mode is the chat execution pipeline: every chat request travels'),
    'Queue mode is the chat execution pipeline.',
  );
});

test('oneSentence cuts a long sentence at a word', () => {
  const long = `${'word '.repeat(80).trim()}.`;
  const cut = oneSentence(long);
  assert.ok(cut.length <= 223);
  assert.ok(cut.endsWith('word...'));
});

test('bodyOf removes front matter and MDX imports, and leaves code alone', () => {
  const source = [
    '---',
    'title: Page',
    '---',
    "import Tabs from '@theme/Tabs';",
    '',
    '# Page',
    '',
    `${FENCE3}ts`,
    "import { Agent } from 'agents';",
    FENCE3,
  ].join('\n');
  assert.equal(bodyOf(source), ['# Page', '', `${FENCE3}ts`, "import { Agent } from 'agents';", FENCE3].join('\n'));
});

test('a fence closes only on a marker at least as long, with nothing after it', () => {
  // A page that shows a markdown file: the file's own three-backtick block is still code.
  const source = [
    'Before [a](./a.md).',
    `${FENCE4}markdown`,
    '# A skill',
    `${FENCE3}python`,
    "import x from 'y'",
    FENCE3,
    'See [b](./b.md).',
    FENCE4,
    'After [c](./c.md).',
  ].join('\n');
  const seen = [];
  outsideCode(source, (line) => {
    seen.push(line);
    return line;
  });
  assert.deepEqual(seen, ['Before [a](./a.md).', 'After [c](./c.md).']);
  assert.equal(
    rewriteLinks(source, (target) => `X:${target}`),
    source.replace('./a.md', 'X:./a.md').replace('./c.md', 'X:./c.md'),
  );
});

test('openingOf returns the first paragraph of prose, joined', () => {
  const page = [
    '# Sandbox',
    '',
    '![A diagram](/img/sandbox.png)',
    '',
    ':::note',
    '',
    'Not this.',
    '',
    ':::',
    '',
    '- not a list either',
    '',
    'The sandbox gives agents a bounded way to',
    'run code. It has six providers.',
    '',
    'A second paragraph.',
  ].join('\n');
  assert.equal(openingOf(page), 'The sandbox gives agents a bounded way to run code. It has six providers.');
});

test('openingOf reads past a blog post title, banner and truncate marker', () => {
  const post = ['# A post', '', '![The banner headline.](/img/blog/banner.png)', '', '<!-- truncate -->', '', 'The post opens here.'].join('\n');
  assert.equal(openingOf(post), 'The post opens here.');
  assert.equal(openingOf('# Only a title'), '');
});

test('rewriteLinks resolves relative targets and leaves the rest', () => {
  const line = 'A [doc](../api/rest-api#run "Title"), an ![image](/img/x.png), [out](https://e.com), [mail](mailto:a@b.c) and [here](#top).';
  assert.equal(
    rewriteLinks(line, (target) => `https://site${target.replace('..', '')}`),
    'A [doc](https://site/api/rest-api#run "Title"), an ![image](https://site/img/x.png), [out](https://e.com), [mail](mailto:a@b.c) and [here](#top).',
  );
});
