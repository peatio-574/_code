/* 后台报名管理：固定 HTML + JSON 接口（/admin/api/registrations）
   大分页（1000/5000 条）时使用「虚拟滚动」只渲染可视区域的行，避免卡顿。 */
(function () {
    'use strict';

    var tbody = document.getElementById('reg_tbody');
    var scrollBox = document.querySelector('.list-scroll');
    var pagination = document.getElementById('pagination');
    var totalEl = document.getElementById('total');
    var perPageEl = document.getElementById('perPage');
    var gotoEl = document.getElementById('gotoPage');
    var searchQ = document.getElementById('search_q');
    var searchInstitution = document.getElementById('search_institution');

    var state = { page: 1, per_page: 20, q: '', institution: '' };
    var ROW_H = 48;              // 与 .reg-table tbody td 高度一致
    var allItems = [];
    var selectedIds = {};        // 勾选集合（跨虚拟滚动保持）

    function td(text, cls) {
        var el = document.createElement('td');
        if (cls) el.className = cls;
        el.textContent = (text === null || text === undefined) ? '' : text;
        return el;
    }

    function checkCell(item) {
        var el = document.createElement('td');
        el.className = 'check';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'row-check';
        cb.value = item.id;
        cb.checked = !!selectedIds[item.id];
        cb.addEventListener('change', function () {
            if (this.checked) selectedIds[item.id] = true; else delete selectedIds[item.id];
            updateBatchState();
        });
        el.appendChild(cb);
        return el;
    }

    function actionCell(item) {
        var el = document.createElement('td');
        el.className = 'op nowrap';
        el.appendChild(linkBtn('查看', function () { openDetail(item); }));
        el.appendChild(linkBtn('编辑', function () { openEdit(item); }));
        el.appendChild(linkBtn('删除', function () { doAction(item.id); }, true));
        return el;
    }

    function linkBtn(text, handler, danger) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'link-btn' + (danger ? ' danger' : '');
        b.textContent = text;
        b.addEventListener('click', handler);
        return b;
    }

    function buildRow(item) {
        var tr = document.createElement('tr');
        tr.appendChild(checkCell(item));
        tr.appendChild(td(item.institution));
        tr.appendChild(td(item.name));
        tr.appendChild(td(item.gender));
        tr.appendChild(td(item.ethnicity));
        tr.appendChild(td(item.nationality));
        tr.appendChild(td(item.id_card));
        tr.appendChild(td(item.subject));
        tr.appendChild(td(item.level));
        tr.appendChild(td(item.created_at));
        tr.appendChild(actionCell(item));
        return tr;
    }

    function emptyRow(text) {
        var tr = document.createElement('tr');
        var cell = document.createElement('td');
        cell.colSpan = 11;
        cell.className = 'empty';
        cell.textContent = text;
        tr.appendChild(cell);
        return tr;
    }

    function spacerRow(height) {
        var tr = document.createElement('tr');
        tr.className = 'v-spacer';
        var cell = document.createElement('td');
        cell.colSpan = 11;
        cell.style.height = height + 'px';
        tr.appendChild(cell);
        return tr;
    }

    /* 只渲染可视区域的行（虚拟滚动）。
       关键：用 replaceChildren(fragment) 原子替换 tbody 内容，
       避免先清空导致表格高度塌陷、scrollTop 被夹回 0 的滚动异常。 */
    var lastRange = { start: -1, end: -1, n: -1 };
    function renderWindow(force) {
        var n = allItems.length;
        if (!n) {
            lastRange = { start: -1, end: -1, n: -1 };
            var fe = document.createDocumentFragment();
            fe.appendChild(emptyRow('暂无报名数据'));
            tbody.replaceChildren(fe);
            return;
        }

        // 数据量不大时直接全量渲染
        if (n <= 150) {
            if (!force && lastRange.n === n && lastRange.start === 0 && lastRange.end === n) return;
            lastRange = { start: 0, end: n, n: n };
            var fa = document.createDocumentFragment();
            for (var k = 0; k < n; k++) fa.appendChild(buildRow(allItems[k]));
            tbody.replaceChildren(fa);
            updateBatchState();
            return;
        }

        var scrollTop = scrollBox ? scrollBox.scrollTop : 0;
        var viewH = scrollBox ? scrollBox.clientHeight : 800;
        var start = Math.max(0, Math.floor(scrollTop / ROW_H) - 8);
        var end = Math.min(n, Math.ceil((scrollTop + viewH) / ROW_H) + 8);
        // 可视区间未变化则跳过重建（force=true 时强制刷新，如全选/取消全选）
        if (!force && lastRange.n === n && lastRange.start === start && lastRange.end === end) return;
        lastRange = { start: start, end: end, n: n };

        var frag = document.createDocumentFragment();
        if (start > 0) frag.appendChild(spacerRow(start * ROW_H));
        for (var i = start; i < end; i++) frag.appendChild(buildRow(allItems[i]));
        if (end < n) frag.appendChild(spacerRow((n - end) * ROW_H));
        tbody.replaceChildren(frag);
        updateBatchState();
    }

    function fillRows(list) {
        allItems = list || [];
        lastRange = { start: -1, end: -1, n: -1 };
        if (scrollBox) scrollBox.scrollTop = 0;
        renderWindow();
    }

    var ticking = false;
    if (scrollBox) {
        scrollBox.addEventListener('scroll', function () {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(function () { ticking = false; renderWindow(); });
        });
    }

    /* ---------- 分页 ---------- */
    function pageLink(label, page, disabled, active) {
        var a = document.createElement('a');
        a.className = 'page-link' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
        a.href = '#';
        a.textContent = label;
        a.addEventListener('click', function (e) {
            e.preventDefault();
            if (!disabled && !active && page) { state.page = page; render(); }
        });
        return a;
    }
    function ellipsis() {
        var s = document.createElement('span');
        s.className = 'page-ellipsis';
        s.textContent = '…';
        return s;
    }
    function renderPagination(pg) {
        pagination.innerHTML = '';
        if (gotoEl) { gotoEl.max = pg.pages || 1; gotoEl.value = pg.page; }
        if (!pg || pg.pages <= 1) return;
        pagination.appendChild(pageLink('上一页', pg.prev_num, !pg.has_prev, false));
        var start = Math.max(1, pg.page - 2);
        var end = Math.min(pg.pages, pg.page + 2);
        if (start > 1) {
            pagination.appendChild(pageLink('1', 1, false, pg.page === 1));
            if (start > 2) pagination.appendChild(ellipsis());
        }
        for (var p = start; p <= end; p++) {
            pagination.appendChild(pageLink(String(p), p, false, p === pg.page));
        }
        if (end < pg.pages) {
            if (end < pg.pages - 1) pagination.appendChild(ellipsis());
            pagination.appendChild(pageLink(String(pg.pages), pg.pages, false, pg.page === pg.pages));
        }
        pagination.appendChild(pageLink('下一页', pg.next_num, !pg.has_next, false));
    }

    /* ---------- 数据加载 ---------- */
    function render() {
        var qs = 'page=' + state.page + '&per_page=' + state.per_page +
            '&q=' + encodeURIComponent(state.q) +
            '&institution=' + encodeURIComponent(state.institution);
        return fetch('/admin/api/registrations?' + qs, { credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 401) { window.location = '/admin/login'; throw new Error('unauthorized'); }
                return r.json();
            })
            .then(function (res) {
                if (!res.success) { fillRows([]); return; }
                fillRows(res.data || []);
                renderPagination(res.pagination);
                if (totalEl) totalEl.textContent = res.pagination.total;
            })
            .catch(function () {});
    }

    function doAction(id) {
        if (!window.confirm('确定要删除该报名信息吗？')) return;
        fetch('/admin/registration/' + id + '/delete', { method: 'POST', credentials: 'same-origin' })
            .then(function () { delete selectedIds[id]; render(); })
            .catch(function () { alert('操作失败，请重试'); });
    }

    /* ---------- 详情弹窗 ---------- */
    var detailModal = document.getElementById('detail_modal');
    var currentDetailItem = null;

    function setText(id, value) {
        var el = document.getElementById(id);
        if (el) el.textContent = (value === null || value === undefined || value === '') ? '—' : value;
    }

    function openDetail(item) {
        currentDetailItem = item;
        setText('d_name', item.name);
        setText('d_gender', item.gender);
        setText('d_ethnicity', item.ethnicity);
        setText('d_nationality', item.nationality);
        setText('d_id_card', item.id_card);
        setText('d_institution', item.institution);
        setText('d_subject', item.subject);
        setText('d_level', item.level);
        setText('d_created_at', item.created_at);
        if (detailModal) detailModal.style.display = 'flex';
    }
    function closeDetail() { if (detailModal) detailModal.style.display = 'none'; }

    var dc = document.getElementById('detail_modal_close');
    var dclose = document.getElementById('detail_close');
    if (dc) dc.addEventListener('click', closeDetail);
    if (dclose) dclose.addEventListener('click', closeDetail);
    if (detailModal) detailModal.addEventListener('click', function (e) { if (e.target === detailModal) closeDetail(); });
    var detailEditBtn = document.getElementById('detail_edit');
    if (detailEditBtn) detailEditBtn.addEventListener('click', function () {
        if (currentDetailItem) { closeDetail(); openEdit(currentDetailItem); }
    });

    /* ---------- 编辑弹窗 ---------- */
    var editModal = document.getElementById('edit_modal');
    var editForm = document.getElementById('edit_form');
    var editId = null;

    function openEdit(item) {
        editId = item.id;
        if (!editForm) return;
        editForm.elements['name'].value = item.name || '';
        editForm.elements['gender'].value = item.gender || '';
        editForm.elements['ethnicity'].value = item.ethnicity || '';
        editForm.elements['nationality'].value = item.nationality || '';
        editForm.elements['id_card'].value = item.id_card || '';
        editForm.elements['subject'].value = item.subject || '';
        editForm.elements['level'].value = item.level || '';
        if (editModal) editModal.style.display = 'flex';
    }
    function closeEdit() { if (editModal) editModal.style.display = 'none'; editId = null; }

    function saveEdit() {
        if (!editForm || editId === null) return;
        var name = editForm.elements['name'].value.trim();
        if (!name) { alert('请填写考生姓名'); return; }
        var fd = new FormData();
        fd.append('name', name);
        fd.append('gender', editForm.elements['gender'].value);
        fd.append('ethnicity', editForm.elements['ethnicity'].value.trim());
        fd.append('nationality', editForm.elements['nationality'].value.trim());
        fd.append('id_card', editForm.elements['id_card'].value.trim().toUpperCase());
        fd.append('subject', editForm.elements['subject'].value.trim());
        fd.append('level', editForm.elements['level'].value.trim());
        fetch('/admin/api/registration/' + editId, { method: 'POST', credentials: 'same-origin', body: fd })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.success) { closeEdit(); updateItem(res.data); }
                else { alert(res.message || '保存失败'); }
            })
            .catch(function () { alert('保存失败，请重试'); });
    }

    function updateItem(data) {
        if (!data) { render(); return; }
        for (var i = 0; i < allItems.length; i++) {
            if (allItems[i].id === data.id) { allItems[i] = data; break; }
        }
        renderWindow(true);
    }

    var editClose = document.getElementById('edit_modal_close');
    var editCancel = document.getElementById('edit_cancel');
    var editSave = document.getElementById('edit_save');
    if (editClose) editClose.addEventListener('click', closeEdit);
    if (editCancel) editCancel.addEventListener('click', closeEdit);
    if (editSave) editSave.addEventListener('click', saveEdit);
    if (editModal) editModal.addEventListener('click', function (e) { if (e.target === editModal) closeEdit(); });

    /* ---------- 批量删除 / 导出 ---------- */
    var checkAll = document.getElementById('check_all');
    var btnBatch = document.getElementById('btn_batch_delete');
    var btnExport = document.getElementById('btn_export');

    function selectedList() { return Object.keys(selectedIds); }

    function updateBatchState() {
        var count = selectedList().length;
        if (checkAll) {
            checkAll.checked = allItems.length > 0 && count === allItems.length;
            checkAll.indeterminate = count > 0 && count < allItems.length;
        }
        if (btnBatch) {
            var label = btnBatch.getAttribute('data-label') || '批量删除';
            btnBatch.textContent = count > 0 ? (label + '(' + count + ')') : label;
            btnBatch.disabled = count === 0;
        }
    }

    function exportData() {
        var ids = selectedList().map(function (v) { return parseInt(v, 10); });
        if (ids.length === 0) { window.location = '/admin/registrations/export'; return; }
        fetch('/admin/registrations/export', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: ids })
        })
            .then(function (r) { if (!r.ok) throw new Error('export failed'); return r.blob(); })
            .then(function (blob) {
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url; a.download = '报名数据导出.xlsx';
                document.body.appendChild(a); a.click(); a.remove();
                URL.revokeObjectURL(url);
            })
            .catch(function () { alert('导出失败，请重试'); });
    }
    if (btnExport) btnExport.addEventListener('click', exportData);

    if (checkAll) {
        checkAll.addEventListener('change', function () {
            if (checkAll.checked) { allItems.forEach(function (it) { selectedIds[it.id] = true; }); }
            else { allItems.forEach(function (it) { delete selectedIds[it.id]; }); }
            renderWindow(true);
        });
    }
    if (btnBatch) {
        btnBatch.addEventListener('click', function () {
            var ids = selectedList().map(function (v) { return parseInt(v, 10); });
            if (ids.length === 0) { alert('请先选择要删除的报名'); return; }
            if (!window.confirm('确定要删除选中的 ' + ids.length + ' 条报名吗？')) return;
            fetch('/admin/registrations/batch_delete', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: ids })
            })
                .then(function (r) { return r.json(); })
                .then(function (res) {
                    if (res.success) { selectedIds = {}; render(); }
                    else { alert(res.message || '删除失败'); }
                })
                .catch(function () { alert('删除失败，请重试'); });
        });
    }

    /* ---------- 搜索 / 分页控件 ---------- */
    var btnSearch = document.getElementById('btn_search');
    if (btnSearch) btnSearch.addEventListener('click', function () {
        state.q = searchQ ? searchQ.value.trim() : '';
        state.institution = searchInstitution ? searchInstitution.value : '';
        state.page = 1; render();
    });
    var btnReset = document.getElementById('btn_reset');
    if (btnReset) btnReset.addEventListener('click', function () {
        state.q = ''; state.institution = ''; state.page = 1;
        if (searchQ) searchQ.value = '';
        if (searchInstitution) searchInstitution.value = '';
        render();
    });
    if (searchQ) searchQ.addEventListener('keyup', function (e) {
        if (e.keyCode === 13) { state.q = searchQ.value.trim(); state.page = 1; render(); }
    });
    if (perPageEl) perPageEl.addEventListener('change', function () {
        state.per_page = parseInt(perPageEl.value, 10) || 20;
        state.page = 1; render();
    });
    function gotoPage() {
        if (!gotoEl) return;
        var page = parseInt(gotoEl.value, 10);
        if (isNaN(page)) return;
        var max = parseInt(gotoEl.max, 10) || 1;
        if (page < 1) page = 1;
        if (page > max) page = max;
        if (page !== state.page) { state.page = page; render(); }
    }
    var btnGoto = document.getElementById('btn_goto');
    if (btnGoto) btnGoto.addEventListener('click', gotoPage);
    if (gotoEl) gotoEl.addEventListener('keyup', function (e) { if (e.keyCode === 13) gotoPage(); });

    render();
})();
