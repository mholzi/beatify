/**
 * #3537: Step 1 shows a short speaker list on its own; the rest sits behind a
 * collapsed "Show N more speakers" row, and a manage view stores which
 * speakers show here.
 */
import { describe, it, expect } from 'vitest';
import {
    splitSpeakers,
    defaultVisible,
    buildOverrides,
    groupByPlatform,
    moreRowHtml,
    manageEntryHtml,
    manageViewHtml,
} from '../admin/speaker-shortlist.js';

// Translate with the fallback, filling {placeholders} like BeatifyI18n.
const t = (key, fallback, params = {}) =>
    fallback.replace(/\{(\w+)\}/g, (_, k) => (k in params ? String(params[k]) : `{${k}}`));
const platformLabel = (p) => ({ music_assistant: 'Music Assistant', sonos: 'Sonos' }[p] || p);

const MA_LIVING = { entity_id: 'media_player.living_ma', friendly_name: 'Living Room', platform: 'music_assistant', shortlisted: true, duplicate_of: null, visibility_override: null };
const MA_KITCHEN = { entity_id: 'media_player.kitchen_ma', friendly_name: 'Kitchen', platform: 'music_assistant', shortlisted: true, duplicate_of: null, visibility_override: null };
const SONOS_LIVING = { entity_id: 'media_player.living', friendly_name: 'Living Room', platform: 'sonos', shortlisted: false, duplicate_of: 'media_player.living_ma', visibility_override: null };
const SONOS_OFFICE = { entity_id: 'media_player.office', friendly_name: 'Office', platform: 'sonos', shortlisted: false, duplicate_of: null, visibility_override: 'hidden' };
const ALL = [MA_LIVING, SONOS_LIVING, MA_KITCHEN, SONOS_OFFICE];

describe('splitSpeakers: the short list and the collapsed rest', () => {
    it('puts duplicates and hidden speakers behind "show more"', () => {
        const { short, more } = splitSpeakers(ALL, null);
        expect(short.map((p) => p.entity_id)).toEqual(['media_player.living_ma', 'media_player.kitchen_ma']);
        expect(more.map((p) => p.entity_id)).toEqual(['media_player.living', 'media_player.office']);
    });

    it('never hides the selected speaker', () => {
        const { short, more } = splitSpeakers(ALL, 'media_player.living');
        expect(short.map((p) => p.entity_id)).toContain('media_player.living');
        expect(more.map((p) => p.entity_id)).toEqual(['media_player.office']);
    });

    it('shows everything from a server that sends no shortlist field', () => {
        const old = ALL.map(({ shortlisted, ...rest }) => rest);
        expect(splitSpeakers(old, null).more).toEqual([]);
    });
});

describe('moreRowHtml: the collapse row', () => {
    it('is absent when nothing is hidden', () => {
        expect(moreRowHtml(0, false, t)).toBe('');
    });

    it('collapsed: says how many, aria-expanded=false', () => {
        const html = moreRowHtml(9, false, t);
        expect(html).toContain('Show 9 more speakers');
        expect(html).toContain('Duplicates and speakers you hid');
        expect(html).toContain('aria-expanded="false"');
        expect(html).not.toContain('is-expanded');
    });

    it('singular for one speaker', () => {
        expect(moreRowHtml(1, false, t)).toContain('Show 1 more speaker<');
    });

    it('expanded: offers to show fewer, aria-expanded=true', () => {
        const html = moreRowHtml(2, true, t);
        expect(html).toContain('Show fewer speakers');
        expect(html).toContain('aria-expanded="true"');
        expect(html).toContain('is-expanded');
    });

    it('carries no data-entity-id, so a tap never selects a speaker', () => {
        expect(moreRowHtml(2, false, t)).not.toContain('data-entity-id');
        expect(manageEntryHtml(t)).not.toContain('data-entity-id');
    });
});

describe('manage view', () => {
    it('starts each switch on the admin choice, else the automatic rule', () => {
        expect(defaultVisible(MA_LIVING)).toBe(true);
        expect(defaultVisible(SONOS_LIVING)).toBe(false);  // duplicate
        expect(defaultVisible(SONOS_OFFICE)).toBe(false);  // hidden by the admin
        expect(defaultVisible({ ...SONOS_LIVING, visibility_override: 'shown' })).toBe(true);
    });

    it('groups by integration, Music Assistant first', () => {
        expect(groupByPlatform(ALL).map((g) => g.platform)).toEqual(['music_assistant', 'sonos']);
    });

    it('renders one switch per speaker, duplicates marked', () => {
        const draft = Object.fromEntries(ALL.map((p) => [p.entity_id, defaultVisible(p)]));
        const html = manageViewHtml(ALL, draft, { t, platformLabel });
        expect((html.match(/role="switch"/g) || []).length).toBe(4);
        expect(html).toContain('Music Assistant');
        expect(html).toContain('Sonos <span class="wiz-dup-chip">1 duplicate</span>');
        expect(html).toContain('Duplicate of Living Room');
        expect(html).toMatch(/data-vis-id="media_player\.living_ma"/);
        expect(html).toMatch(/aria-checked="true" data-vis-id="media_player\.living_ma"/);
        expect(html).toMatch(/aria-checked="false" data-vis-id="media_player\.living"/);
        expect(html).toContain('Save · 2 speakers shown');
        expect(html).toContain('Cancel');
    });

    it('escapes speaker names from the network', () => {
        const evil = { ...MA_KITCHEN, friendly_name: '<img src=x onerror=alert(1)>' };
        const html = manageViewHtml([evil], {}, { t, platformLabel });
        expect(html).not.toContain('<img');
        expect(html).toContain('&lt;img');
    });

    it('shows a save error when there is one', () => {
        const html = manageViewHtml(ALL, {}, { t, platformLabel, error: 'Nope' });
        expect(html).toContain('role="alert"');
        expect(html).toContain('Nope');
    });
});

describe('buildOverrides: only what differs from the automatic rule is stored', () => {
    it('stores nothing when the switches match the rule', () => {
        const draft = { 'media_player.living_ma': true, 'media_player.living': false, 'media_player.kitchen_ma': true, 'media_player.office': true };
        expect(buildOverrides(ALL, draft)).toEqual({ shown: [], hidden: [] });
    });

    it('a duplicate switched on is "shown", a normal speaker switched off is "hidden"', () => {
        const draft = { 'media_player.living': true, 'media_player.kitchen_ma': false };
        expect(buildOverrides(ALL, draft)).toEqual({
            shown: ['media_player.living'],
            hidden: ['media_player.kitchen_ma', 'media_player.office'],
        });
    });

    it('keeps the stored choice for speakers that are not in the list now', () => {
        const previous = { shown: ['media_player.garden'], hidden: ['media_player.garage', 'media_player.office'] };
        const out = buildOverrides(ALL, { 'media_player.office': true }, previous);
        expect(out).toEqual({ shown: ['media_player.garden'], hidden: ['media_player.garage'] });
    });
});
