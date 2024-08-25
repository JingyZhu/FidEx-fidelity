"""
Check if the archive preserves all the fidelity from liveweb page
"""
import difflib
import json
import re, os
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, Tag
from collections import defaultdict
import cv2
import numpy as np
from urllib.parse import unquote, urlsplit, urlunsplit

import sys
cur_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(cur_dir))
from utils import url_utils
import warnings
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

def _sibling_xpath(path1, path2, max_diff=1):
    """Check if path1 and path2 are siblings (same length, differ by one element)
    
    Arguments:
        max_diff (int): Max number of different elements for path to be considered as "sibling" (default 1)
    """
    path1 = path1.split('/')
    path2 = path2.split('/')
    if len(path1) != len(path2):
        return False
    diff = 0
    for p1, p2 in zip(path1, path2):
        e1 = p1.split('[')[0]
        e2 = p2.split('[')[0]
        if e1 != e2:
            return False
        if p1 != p2:
            diff += 1
    return diff <= max_diff

def compare_screenshot(live_img, archive_img):
    if not os.path.exists(live_img) or not os.path.exists(archive_img):
        return -1
    img1 = cv2.imread(live_img)
    img2 = cv2.imread(archive_img)
    height = min(img1.shape[0], img2.shape[0])
    width = min([img1.shape[1], img2.shape[1]])
    img1 = img1[:height,:width,:]
    img2 = img2[:height,:width,:]
    diff = img1 - img2
    total = img1.shape[0]*img1.shape[1]*img1.shape[2]
    same = np.count_nonzero(diff == 0)
    return same / total


def _collect_dimension(element):
    if 'dimension' not in element or element['dimension'] is None:
        return {}
    return {
        'width': element['dimension']['width'],
        'height': element['dimension']['height']
    }


class htmlElement:
    def __init__(self, element: dict):
        self.xpath = element['xpath']
        self.text = element['text']
        self.tag = self._get_tag()
        self.dynamic = self._is_dynamic()
        self.in_carousel = self._in_carousel()
        self.features = self.features()
        self.dimension = _collect_dimension(element)
    
    def _norm_href(self, href):
        if href is None:
            return None
        href = href.strip()
        non_target_prefix = ['javascript:', 'mailto:', 'tel:', 'sms:']
        for c in non_target_prefix:
            if href.startswith(c):
                return None
        # If the href is puny encoded or percent encoded, decode it
        i = 0
        while i < 3 and '%' in href:
            href = unquote(href)
            i += 1
        if href.endswith('#'):
            href = href[:-1]
        return href

    def _get_src(self, img):
        src = img.attrs.get('src')
        if src is None:
            return None
        us = urlsplit(src)
        if us.query or us.fragment:
            us = us._replace(query='', fragment='')
            src = urlunsplit(us)
        i = 0
        while i < 3 and '%' in src:
            src = unquote(src)
            i += 1
        return src
    
    def _get_tag(self):
        """Extract tag name from the text"""
        tag = BeautifulSoup(self.text, 'html.parser').find()
        if tag is None:
            tagname = self.xpath.split('/')[-1].split('[')[0]
            return tagname
        return tag
    
    def _is_dynamic(self):
        assert(hasattr(self, 'tag'))
        if not isinstance(self.tag, Tag):
            return False
        style = self.tag.attrs.get('style', '')
        for s in style.split(';'):
            if 'transform' in s:
                return True
        spin_keywords = ['spin']
        for k in spin_keywords:
            if k in self.text.lower():
                return True
        return False
    
    def _in_carousel(self):
        """Heuristic to decide if the element is part of the carousel"""
        assert(hasattr(self, 'tag'))
        if self.tag == '#text':
            return False
        class_keywords = ['carousel', 'slider', 'slideshow', 'gallery', 'slick', 'swiper']
        for c in class_keywords:
            if c in self.text.lower():
                return True
        

    def features(self):
        """Collect tag name and other important attributes that matters to the rendering"""
        all_rules = [] # List of lambda func to get the attribute
        tag_rules = {
            'img': [lambda img: self._get_src(img)],
            'a': [
                # lambda a: a.attrs.get('class'), 
                lambda a: self._norm_href(a.attrs.get('href'))],
        }
        if isinstance(self.tag, str):
            return tuple([self.tag])
        tag = self.tag
        tagname = tag.name
        features = [tagname]
        rules = tag_rules.get(tagname, []) + all_rules
        for r in rules:
            tag_r = r(tag)
            if tag_r is not None:
                features.append(tag_r)
        # * Add style and throw away certain attr
        def _filter_style(style):
            new_style = []
            filter_keys = [
                            'background',
                            'background-image', 
                            'opacity', 
                            'width', 
                            'height',
                            'left',
                            'top', 
                            'display', 
                            'transform',
                            'transition'
                        ]
            for s in style.split(';'):
                to_filter = False
                for k in filter_keys:
                    if k in s.split(':')[0]:
                        to_filter = True
                        break
                if not to_filter:
                    new_style.append(s)
            return ';'.join(new_style)
        if 'style' in tag.attrs and tag.attrs['style'] != '':
            style = _filter_style(tag.attrs['style'])
            if len(style) > 0:
                features.append(style)
        return tuple(features)
    
    def __eq__(self, other):
        def dimension_eq(d1, d2):
            d1w, d1h = d1.get('width', 1), d1.get('height', 1)
            d2w, d2h = d2.get('width', 1), d2.get('height', 1)
            wdiff = abs(d1w - d2w) / max(d1w, d2w)
            hdiff = abs(d1h - d2h) / max(d1h, d2h)
            return wdiff <= 0.05 and hdiff <= 0.05

        def features_eq(e1, e2):
            if e1.features[0].lower() == 'a' and e2.features[0].lower() == 'a':
                identical = True
                if len(e1.features) != len(e2.features):
                    return False
                for f1, f2 in zip(e1.features, e2.features):
                    if type(f1) != str or type(f2) != str:
                        identical = identical and f1 == f2
                        continue
                    identical = identical and (f1.endswith(f2) or f2.endswith(f1))
                return identical
            elif e1.features[0].lower() == '#text' and e2.features[0].lower() == '#text':
                return e1.text == e2.text
            else:
                return e1.features == e2.features

        def dynamic_eq(e1, e2):
            if not e1.dynamic or not e2.dynamic:
                return False
            if e1.xpath == e2.xpath:
                return True
            # remove style in text
            e1_text = re.sub(r'style=".*?"', '', e1.text)
            e2_text = re.sub(r'style=".*?"', '', e2.text)
            if e1_text == e2_text:
                return True
            return False
        
        def carousel_eq(e1, e2):
            if not e1.in_carousel or not e2.in_carousel:
                return False
            if e1.xpath == e2.xpath:
                return True
            # Dimension has the same top, width and height
            if e1.dimension.get('top', 1) == e2.dimension.get('top', 2) and dimension_eq(e1.dimension, e2.dimension):
                return True
            return False
        
        if carousel_eq(self, other):
            return True
        elif dynamic_eq(self, other):
            return True
        else:
            return features_eq(self, other) and dimension_eq(self.dimension, other.dimension)

    def __hash__(self) -> int:
        return hash((self.xpath, self.text, self.dimension.get('width', 0), self.dimension.get('height', 0)))

    def __repr__(self) -> str:
        return f"{self.xpath} {self.text} {self.dimension}"


def _html_2_xpath(html, element):
    """Translate each line in html to xpath"""
    lines = html.split('\n')
    xpaths = []
    for line in lines:
        line = line.strip()
        # Match the first number before :
        idx = re.search(r'^\d+:', line)
        idx = idx.group()[:-1] if idx else None
        if idx is None:
            continue
        xpath = element[int(idx)]
        xpaths.append(xpath)
    return xpaths

def _diff_html(left_html: "List[element]", right_html: "List[element]"):
    """
    Compute the diff between left_html and right_html by computing the longest common subsequence
    
    Returns:
        (List[str], List[str]): List of xpaths that are different, for live and archive respectively.
    """
    left_html = [htmlElement(e) for e in left_html]
    right_html = [htmlElement(e) for e in right_html]
    # Apply longest common subsequence to get the diff of live and archive htmls
    lcs_lengths = [[0 for _ in range(len(right_html) + 1)] for _ in range(len(left_html) + 1)]
    for i, left_elem in enumerate(left_html, 1):
        for j, right_elem in enumerate(right_html, 1):
            if left_elem == right_elem:
                lcs_lengths[i][j] = lcs_lengths[i-1][j-1] + 1
            else:
                lcs_lengths[i][j] = max(lcs_lengths[i-1][j], lcs_lengths[i][j-1])
    # Backtrack to get the diff
    lcs_live, lcs_archive = [], []
    i, j = len(left_html), len(right_html)
    while i > 0 and j > 0:
        if left_html[i-1] == right_html[j-1]:
            lcs_live.append(left_html[i-1].xpath)
            lcs_archive.append(right_html[j-1].xpath)
            i -= 1
            j -= 1
        # This means left_html[i] is not in the lcs
        elif lcs_lengths[i-1][j] > lcs_lengths[i][j-1]:
            i -= 1
        # Archive_html[j] is not in the lcs
        elif lcs_lengths[i-1][j] < lcs_lengths[i][j-1]:
            j -= 1
        # This case can be either both left_html[i] and right_html[j] are not in the lcs (e.g. abcx and abcy) 
        # or both can be in (e.g. abca and abac)
        else:
            j -= 1
    lcs_live.reverse()
    lcs_archive.reverse()
    left_diff = [e.xpath for e in left_html if e.xpath not in set(lcs_live)]
    right_diff = [e.xpath for e in right_html if e.xpath not in set(lcs_archive)]
    return left_diff, right_diff


def verify(left_element: dict, right_element: dict) -> bool:
    """
    Args:
        left_element (dict): element's path and dimension info in the liveweb page
        right_element (dict): element's path and dimension info in the archive page
    
    Returns:
        fidelity_preserved: Whether the fidelity is preserved
    """
    left_xpaths = [e['xpath'] for e in left_element]
    right_xpaths = [e['xpath'] for e in right_element]
    if left_xpaths != right_xpaths:
        print("html not same")
        print(json.dumps([d for d in
            list(difflib.ndiff(left_xpaths, right_xpaths)) if d[0] in ['-', '+']], indent=2))
        return False
    # * Currently for each element, only check the width and height
    if len(left_element) != len(right_element):
        print("Element number is different")
        return False
    for le, ae in zip(left_element, right_element):
        live_dimension = _collect_dimension(le)
        archive_dimension = _collect_dimension(ae)
        if live_dimension != archive_dimension:
            print("Dimension is different", le, ae)
            return False
    return True

def _merge_xpaths(xpaths):
    """
    Merge the xpaths that have the same prefix
    
    Returns:
        List[List]: List of xpaths that share the same prefix
    """
    xpaths = sorted(xpaths)
    merged_xpaths = []
    for xpath in xpaths:
        if not merged_xpaths:
            merged_xpaths.append([xpath])
            continue
        last = merged_xpaths[-1]
        if xpath.startswith(last[0]):
            last.append(xpath)
        else:
            merged_xpaths.append([xpath])
    return merged_xpaths

def xpaths_2_text(xpaths, xpath_map):
    """Transform xpaths to their text"""
    text = ''
    for xpath in xpaths:
        element = xpath_map[xpath]
        text += '  ' * element['depth'] + element['text'] + '\n'
    return text

def diff(left_element, right_element, returnHTML=False) -> (list, list):
    left_xpaths_map = {e['xpath']: e for e in left_element}
    right_xpaths_map = {e['xpath']: e for e in right_element}
    left_unique, right_unique = _diff_html(left_element, right_element)
    
    left_unique = _merge_xpaths(left_unique)
    # print("left_unique number", [len(xpaths) for xpaths in left_unique])
    if returnHTML:
        left_unique = [xpaths_2_text(xpaths, left_xpaths_map) for xpaths in left_unique]
    
    right_unique = _merge_xpaths(right_unique)
    # print("right_unique number", [len(xpaths) for xpaths in right_unique])
    if returnHTML:
        right_unique = [xpaths_2_text(xpaths, right_xpaths_map) for xpaths in right_unique]
    return left_unique, right_unique


def generate_sig(write, live=False):
    sig = []
    stackInfo = write['stackInfo']
    for stack in stackInfo:
        sig.append([])
        for callFrame in stack['callFrames']:
            url = callFrame['archive_url'] if live else callFrame['url']
            real_url = url_utils.filter_archive(url)
            if real_url in [None, '']:
                continue
            line = callFrame['archive_start'][0] if live else callFrame['lineNumber']
            col = callFrame['archive_start'][1] if live else callFrame['columnNumber']
            frame = f'{real_url}:{line}:{col}'
            sig[-1].append(frame)
    return sig

def diff_writes(left_writes: list, right_writes: list, attribute: str='rawWrites'):
    """
    Diff the writes between live and archive pages
    Same criteria is based on write's stack trace

    Args:
        left_writes: List from left_writes
        right_writes: List from right_writes
    """
    left_writes = left_writes[attribute]
    right_writes = right_writes[attribute]

    def _tag_from_xpath(xpath):
        return xpath.split('/')[-1].split('[')[0]

    def _tag_from_arg(args):
        if not isinstance(args, list):
            args = [args]
        tags = []
        for arg in args:
            if 'xpath' in arg:
                tags.append(_tag_from_xpath(arg['xpath']))
            else:
                html = BeautifulSoup(str(arg['html']), 'html.parser')
                tag = html.find()
                if tag:
                    tags.append(tag.name)
                else:
                    tags.append('text')
        return tags

    left_sigs, right_sigs = defaultdict(list), defaultdict(list)
    for write in left_writes:
        # write_sig = generate_sig(live_stacks_id[write['wid']], live=True)
        write_sig = [write['method']]
        target = _tag_from_xpath(write['xpath'])
        args = []
        for arg in write['arg']:
            args += _tag_from_arg(arg)
        sig = [target] + args + write_sig
        sig = tuple([tuple(s) if isinstance(s, list) else s for s in sig])
        left_sigs[sig].append(write)
    
    for write in right_writes:
        # write_sig = generate_sig(archive_stacks_id[write['wid']], live=False)
        write_sig = [write['method']]
        target = _tag_from_xpath(write['xpath'])
        args = []
        for arg in write['arg']:
            args += _tag_from_arg(arg)
        sig = [target] + args + write_sig
        sig = tuple([tuple(s) if isinstance(s, list) else s for s in sig])
        right_sigs[sig].append(write)
    
    left_unique, right_unique = {}, {}
    for sig in left_sigs:
        if sig not in right_sigs  or len(left_sigs[sig]) > len(right_sigs[sig]):
            left_unique[sig] = left_sigs[sig]
    for sig in right_sigs:
        if sig not in left_sigs or len(right_sigs[sig]) > len(left_sigs[sig]):
            right_unique[sig] = right_sigs[sig]
    return left_unique, right_unique

def associate_writes(element_xpath: str, writes: list) -> list:
    """
    Associate JS writes with the input element
    Add:    1. Parent node append self
    Update: 1. Same node set attribute
            2. Parent node set HTML
    Remove: 1. Same node remove child

    Args:
        element (str): element's xpath
        writes (list): list of writes
    
    Returns:
        list: list of writes that are associated with the element
    """
    # TODO: Potential next step
    # In node_writes_override.js, collect info for beforeIsConnected and afterIsConnected for args
    # When collect info, also collect all args' children and there corresponding xpath
    # When matching, even if the target element is the child of arg, we can find it out, and whether is has any visible effect.                                                

    # Or we can diff the writes between live and archive first (how? may be using target and stackTrace first?)
    # Then only associate writes within the diff parts.

    # Operations that affect element if element is the target
    target_operation = {
        'replaceChild': None,
        'removeChild': None,
        'set:nodeValue': None,
        'set:textContent': None,
        'set:src': None,
        'set:style': None,
        'removeAttribute': None,
        'removeAttributeNode': None,
        'removeAttributeNS': None,
        'replaceChildren': None,
        'replaceWith': None,
        'setAttribute': None,
        'setAttributeNode': None,
        'setAttributeNodeNS': None,
        'setAttributeNS': None,
        'setHTML': None,
        'set:className': None,
        'set:id': None,
        'set:innerHTML': None
    }
    # {operation name: [related arguments idx]}
    # If empty list, all arguments are related
    args_operation = {
        'appendChild': [0],
        'insertBefore': [0],
        'replaceChild': [0],
        'removeChild': [0],
        'after': [],
        'append': [],
        'before': [],
        'remove': [],
        'replaceChildren': [],
        'replaceWith': [],
    }
    # Set HTML operation. Since there is no xpath, need to check separately
    set_html_operation = {
        'setHTML': None,
        'set:innerHTML': None
    }
    
    def target_operation_check(write):
        return write['xpath'] == element_xpath
    
    def args_operation_check(write, idxs):
        args = []
        if len(idxs) == 0:
            args = write['arg']
        else:
            for idx in idxs:
                args.append(write['arg'][idx])
        for arg in args:
            arg = [arg] if not isinstance(arg, list) else arg
            for a in arg:
                if a['html'] in ['#comment']:
                    continue
                if 'xpath' in a and element_xpath.startswith(a['xpath']):
                    return True
        return False

    # TODO: Implement check for set_html_operation
    
    related_writes, related_seen = [], set()
    for write in writes:
        method = write['method']
        if method in target_operation and target_operation_check(write):
            if write['wid'] not in related_seen:
                related_writes.append(write)
                related_seen.add(write['wid'])
    for write in writes:
        method = write['method']
        if method in args_operation and args_operation_check(write, args_operation[method]):
            if write['wid'] not in related_seen:
                related_writes.append(write)
                related_seen.add(write['wid'])
    return related_writes

def meaningful_diff(left_element, left_unique, right_element, right_unique):
    """
    Classify if the unique layout tree is actually meaningfug, not some random noise(e.g. recaptcha)
    Currently, filtration involves:
        - All recaptcha like elements
        - All youtube video elements (class includes "ytp")
        - All vimeo video elements (iframe src includes "player.vimeo.com")
        - Any wrapping element that all the children is matched

    Returns:
        (List, List): updated left_unique and right_unique
    """
    left_xpaths_map = {e['xpath']: e for e in left_element}
    right_xpaths_map = {e['xpath']: e for e in right_element}
    def _ignore_tag(branch):
        ignore_list = ['ruffle-embed', 'rs-progress-bar']
        for xpath in branch:
            for ig in ignore_list:
                if xpath.split('/')[-1].startswith(ig):
                    return True
        return False
        
    def _from_recaptcha(branch, xpaths_map):
        xpath = branch[0]
        # * Check parent
        paths = xpath.split('/')
        iframe_idx = -1
        for i, p in enumerate(paths):
            if p.startswith('iframe'):
                iframe_idx = i
                break
        iframe_path = paths[:iframe_idx+1]
        iframe_element = xpaths_map.get('/'.join(iframe_path), None)
        if iframe_element is not None:
            if 'recaptcha' in iframe_element['text'].lower():
                return True
        # * Check children
        for br in branch:
            element = xpaths_map[br]
            if 'recaptcha' in element['text'].lower():
                return True
        # * Check background
        if len(branch) == 1:
            element = xpaths_map[xpath]
            recaptcha_background = re.compile('<div style="width: 100%; height: 100%; position: fixed; top: 0px; left: 0px; z-index: \d+; background-color: rgb\\(255, 255, 255\\);\\ opacity:\\ 0\\.05;">')
            if recaptcha_background.search(element['text'].lower()):
                return True
        return False

    def _from_youtube(branch, xpaths_map):
        for br in branch:
            element = xpaths_map[br]
            element_tag = BeautifulSoup(element['text'], 'html.parser')
            # if element_tag is pure text continue
            if element_tag.find() is None:
                continue
            # First element's class name includes "ytp"
            if 'ytp' in ' '.join(element_tag.find().attrs.get('class', '')):
                return True
        return False

    def _from_vimeo(branch, xpaths_map):
        xpath = branch[0]
        # * Check parent
        paths = xpath.split('/')
        iframe_idx = -1
        for i, p in enumerate(paths):
            if p.startswith('iframe'):
                iframe_idx = i
                break
        iframe_path = paths[:iframe_idx+1]
        iframe_element = xpaths_map.get('/'.join(iframe_path), None)
        if iframe_element is not None:
            if 'player.vimeo.com' in iframe_element['text'].lower():
                return True
    
    def _remove_wrapping_elements(branch, xpaths_map):
        removed = 1 # dummy first
        cur_branch = branch
        while removed > 0:
            removed = 0
            new_branch = []
            for br in cur_branch:
                has_child = False
                has_xpathmap_child = False
                for b in cur_branch:
                    if b != br and b.startswith(br):
                        has_child = True
                        break
                if has_child:
                    new_branch.append(br)
                    continue
                # Check if xpaths_map has any br's children
                # If so, this mean the br is just a wrapping element, where all the children are matched or ignored
                for b in xpaths_map:
                    if b != br and b.startswith(br):
                        has_xpathmap_child = True
                        removed += 1
                        break
                if not has_xpathmap_child:
                    new_branch.append(br)
            cur_branch = new_branch
        return cur_branch


    new_left_unique = []
    for branch in left_unique:
        branch_meaningful = True
        if _ignore_tag(branch):
            branch_meaningful = False
        if _from_recaptcha(branch, left_xpaths_map):
            branch_meaningful = False
        if _from_youtube(branch, left_xpaths_map):
            branch_meaningful = False
        if _from_vimeo(branch, left_xpaths_map):
            branch_meaningful = False
        if branch_meaningful:
            branch = _remove_wrapping_elements(branch, left_xpaths_map)
            new_left_unique.append(branch) if len(branch) > 0 else None
    
    new_right_unique = []
    for branch in right_unique:
        branch_meaningful = True
        if _ignore_tag(branch):
            branch_meaningful = False
        if _from_recaptcha(branch, right_xpaths_map):
            branch_meaningful = False
        if _from_youtube(branch, right_xpaths_map):
            branch_meaningful = False
        if _from_vimeo(branch, right_xpaths_map):
            branch_meaningful = False
        if branch_meaningful:
            branch = _remove_wrapping_elements(branch, right_xpaths_map)
            new_right_unique.append(branch) if len(branch) > 0 else None

    return new_left_unique, new_right_unique

def filter_dynamism(left_unique, left_writes,
                    right_unique, right_writes):
    """
    Filter out unique elements that are caused by dynamic components
    Currently mainly focus on image carousel with the following heuristics
        - Sibling elements appear at both unique branches
        - For all writes associated with the sibling elements, there are repetitive writes
    
    Returns:
        (List, List): updated left_unique and right_unique
    """
    write_type = 'rawWrites'
    new_left_unique, new_right_unique = [], []
    
    def select_writes(writes, xpaths):
        xpaths_set = set(xpaths)
        new_writes = []
        is_set_class = lambda w: w['method'] == 'setAttribute' and len(w['arg']) == 2 and w['arg'][0]['html'] == 'class'
        is_set_classname = lambda w: w['method'] == 'set:className'
        for write in writes:
            if write['xpath'] not in xpaths_set:
                continue
            if is_set_class(write):
                new_writes.append(write)
            elif is_set_classname(write):
                new_writes.append(write)
        return new_writes
    
    def overlap_write(left_writes, right_writes):
        for left_write in left_writes:
            for right_write in right_writes:
                left_write_info = {'method': left_write['method'], 'arg': left_write['arg']}
                right_write_info = {'method': right_write['method'], 'arg': right_write['arg']}
                if left_write_info == right_write_info:
                    return True
        return False
    
    for left_br in left_unique:
        match_other_unique = False
        for j, right_br in enumerate(right_unique):
            sibling_branch = len(left_br) == len(right_br) \
                           and all([_sibling_xpath(l, r) for l, r in zip(left_br, right_br)])
            if not sibling_branch:
                continue
            left_associate_writes = []
            for l in left_br:
                left_associate_writes += associate_writes(l, left_writes[write_type])
            left_associate_writes = select_writes(left_associate_writes, left_br)
            for r in right_br:
                right_associate_writes = associate_writes(r, right_writes[write_type])
            right_associate_writes = select_writes(right_associate_writes, right_br)
            # print("left associate writes", left_br, json.dumps(left_associate_writes, indent=2))
            # print("right associate writes", right_br, json.dumps(right_associate_writes, indent=2))
            if overlap_write(left_associate_writes, right_associate_writes):
                match_other_unique = True
                right_unique = right_unique[:j] + right_unique[j+1:]
                break
        if not match_other_unique:
            new_left_unique.append(left_br)
    new_right_unique = right_unique
    return new_left_unique, new_right_unique

def filter_same_visual_part(left_img, left_unique, left_elements, 
                            right_img, right_unique, right_elements):
    """
    Filter out unique elements that are have the same screenshot images
    To be defined as "same visual part", the two 
    
    Returns:
        (List, List): updated left_unique and right_unique
    """
    if not os.path.exists(left_img) or not os.path.exists(right_img):
        return left_unique, right_unique
    left_xpaths_map = {e['xpath']: e for e in left_elements}
    right_xpaths_map = {e['xpath']: e for e in right_elements}
    def update_crop(crop, element, img_dimen):
        if element.get('dimension', None) is None:
            return crop
        dimen = element['dimension']
        im_t, im_b, im_l, im_r = 0, img_dimen[0], 0, img_dimen[1]
        t, b, l, r = crop
        t = max(im_t, min(t, dimen['top']))
        b = min(im_b, max(b, dimen['top'] + dimen['height']))
        l = max(im_l, min(l, dimen['left']))
        r = min(im_r, max(r, dimen['left'] + dimen['width']))
        return [t, b, l, r]
    def crop_intersect(crop1, crop2):
        return crop1[0] < crop2[1] and crop1[1] > crop2[0] and crop1[2] < crop2[3] and crop1[3] > crop2[2]
    def branch_crop(branch, xpaths_map, img_dimen):
        crop_area = [float('inf'), float('-inf'), float('inf'), float('-inf')]
        for xpath in branch:
            crop_area = update_crop(crop_area, xpaths_map[xpath], img_dimen)
        return crop_area
    img1 = cv2.imread(left_img)
    img1_dimen = img1.shape[:2]
    img2 = cv2.imread(right_img)
    img2_dimen = img2.shape[:2]
    img_dimen = [min(img1_dimen[0], img2_dimen[0]), min(img1_dimen[1], img2_dimen[1])]
    left_crops, right_crops = [], []
    for left_br in left_unique:
        left_crops.append(branch_crop(left_br, left_xpaths_map, img1_dimen))
    for right_br in right_unique:
        right_crops.append(branch_crop(right_br, right_xpaths_map, img2_dimen))
    
    new_left_unique, new_right_unique = [], []
    for i in range(len(left_unique)):
        matched_crop = False
        for j in range(len(right_unique)):
            left_crpo, right_crop = left_crops[i], right_crops[j]
            if not crop_intersect(left_crpo, right_crop):
                continue
            merged_crop = [min(left_crpo[0], right_crop[0]), min(img_dimen[0], max(left_crpo[1], right_crop[1])),
                            min(left_crpo[2], right_crop[2]), min(img_dimen[1], max(left_crpo[3], right_crop[3]))]
            merged_crop = [int(c) for c in merged_crop]
            left_crop = img1[merged_crop[0]:merged_crop[1], merged_crop[2]:merged_crop[3], :]
            right_crop = img2[merged_crop[0]:merged_crop[1], merged_crop[2]:merged_crop[3], :]
            diff = left_crop - right_crop
            if np.count_nonzero(diff == 0) == diff.shape[0]*diff.shape[1]*diff.shape[2]:
                matched_crop = True
                right_unique = right_unique[:j] + right_unique[j+1:]
                break
        if not matched_crop:
            new_left_unique.append(left_unique[i])
    new_right_unique = right_unique
    return new_left_unique, new_right_unique