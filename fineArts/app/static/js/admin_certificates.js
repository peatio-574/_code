/* 后台证书管理：固定 HTML + JSON 接口（/admin/api/certificates） */
(function () {
    'use strict';

    var tbody = document.getElementById('cert_tbody');
    var pagination = document.getElementById('pagination');
    var totalEl = document.getElementById('total');
    var perPageEl = document.getElementById('perPage');
    var gotoEl = document.getElementById('gotoPage');
    var searchQ = document.getElementById('search_q');
    var searchMajor = document.getElementById('search_major');

    // 状态仅保存在内存，不写入 URL
    var state = {
        page: 1,
        per_page: 20,
        q: '',
        major: ''
    };

    /* ---------- 单元格 ---------- */
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
        cb.addEventListener('change', updateBatchState);
        el.appendChild(cb);
        return el;
    }

    function actionCell(item) {
        var el = document.createElement('td');
        el.className = 'op nowrap';

        var edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'link-btn';
        edit.textContent = '编辑';
        edit.addEventListener('click', function () { openEditModal(item.id); });
        el.appendChild(edit);

        var del = document.createElement('button');
        del.type = 'button';
        del.className = 'link-btn danger';
        del.textContent = '删除';
        del.addEventListener('click', function () { doAction(item.id); });
        el.appendChild(del);

        return el;
    }

    function fillRows(list) {
        tbody.innerHTML = '';
        if (!list || list.length === 0) {
            var tr = document.createElement('tr');
            var cell = document.createElement('td');
            cell.colSpan = 10;
            cell.className = 'empty';
            cell.textContent = '暂无数据';
            tr.appendChild(cell);
            tbody.appendChild(tr);
            return;
        }
        list.forEach(function (item) {
            var tr = document.createElement('tr');
            tr.appendChild(checkCell(item));
            tr.appendChild(td(item.name));
            tr.appendChild(td(item.issue_date));
            tr.appendChild(td(item.major));
            tr.appendChild(td(item.level));
            tr.appendChild(td(item.org));
            tr.appendChild(td(item.id_card));
            tr.appendChild(td(item.cert_no));
            tr.appendChild(td(item.updated_at));
            tr.appendChild(actionCell(item));
            tbody.appendChild(tr);
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
            if (!disabled && !active && page) {
                state.page = page;
                render();
            }
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
        if (gotoEl) {
            gotoEl.max = pg.pages || 1;
            gotoEl.value = pg.page;
        }
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
        var qs = 'page=' + state.page +
            '&per_page=' + state.per_page +
            '&q=' + encodeURIComponent(state.q) +
            '&major=' + encodeURIComponent(state.major);

        return fetch('/admin/api/certificates?' + qs, { credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 401) { window.location = '/admin/login'; throw new Error('unauthorized'); }
                return r.json();
            })
            .then(function (res) {
                if (!res.success) {
                    fillRows([]);
                    return;
                }
                fillRows(res.data || []);
                renderPagination(res.pagination);
                if (totalEl) totalEl.textContent = res.pagination.total;
                updateBatchState();
            })
            .catch(function () { /* 已跳转或网络异常 */ });
    }

    function doAction(id) {
        if (!window.confirm('确定要删除该证书吗？')) return;
        fetch('/admin/certificate/' + id + '/delete', { method: 'POST', credentials: 'same-origin' })
            .then(function () { render(); })
            .catch(function () { alert('操作失败，请重试'); });
    }

    /* ---------- 批量删除 ---------- */
    var checkAll = document.getElementById('check_all');
    var btnBatch = document.getElementById('btn_batch_delete');
    var btnExport = document.getElementById('btn_export');

    function selectedChecks() {
        return document.querySelectorAll('#cert_tbody .row-check:checked');
    }

    function updateBatchState() {
        var all = document.querySelectorAll('#cert_tbody .row-check');
        var checked = selectedChecks();
        if (checkAll) {
            checkAll.checked = all.length > 0 && checked.length === all.length;
            checkAll.indeterminate = checked.length > 0 && checked.length < all.length;
        }
        if (btnBatch) {
            var label = btnBatch.getAttribute('data-label') || '批量删除';
            btnBatch.textContent = checked.length > 0 ? (label + '(' + checked.length + ')') : label;
            btnBatch.disabled = checked.length === 0;
        }
    }

    // 导出：未勾选导出全部；勾选则只导出勾选的数据
    function exportData() {
        var checked = selectedChecks();
        if (checked.length === 0) {
            window.location = '/admin/certificates/export';
            return;
        }
        var ids = Array.prototype.map.call(checked, function (cb) { return parseInt(cb.value, 10); });
        fetch('/admin/certificates/export', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: ids })
        })
            .then(function (r) {
                if (!r.ok) throw new Error('export failed');
                return r.blob();
            })
            .then(function (blob) {
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                a.download = '证书数据导出.xlsx';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
            })
            .catch(function () { alert('导出失败，请重试'); });
    }

    if (btnExport) btnExport.addEventListener('click', exportData);

    if (checkAll) {
        checkAll.addEventListener('change', function () {
            document.querySelectorAll('#cert_tbody .row-check').forEach(function (cb) {
                cb.checked = checkAll.checked;
            });
            updateBatchState();
        });
    }

    if (btnBatch) {
        btnBatch.addEventListener('click', function () {
            var checked = selectedChecks();
            if (checked.length === 0) { alert('请先选择要删除的证书'); return; }
            var ids = Array.prototype.map.call(checked, function (cb) { return parseInt(cb.value, 10); });
            if (!window.confirm('确定要删除选中的 ' + ids.length + ' 条证书吗？')) return;

            fetch('/admin/certificates/batch_delete', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: ids })
            })
                .then(function (r) { return r.json(); })
                .then(function (res) {
                    if (res.success) { render(); }
                    else { alert(res.message || '删除失败'); }
                })
                .catch(function () { alert('删除失败，请重试'); });
        });
    }

    /* ---------- 搜索 / 重置 / 每页 / 跳转 ---------- */
    var btnSearch = document.getElementById('btn_search');
    if (btnSearch) {
        btnSearch.addEventListener('click', function () {
            state.q = searchQ ? searchQ.value.trim() : '';
            state.major = searchMajor ? searchMajor.value : '';
            state.page = 1;
            render();
        });
    }

    var btnReset = document.getElementById('btn_reset');
    if (btnReset) {
        btnReset.addEventListener('click', function () {
            state.q = '';
            state.major = '';
            state.page = 1;
            if (searchQ) searchQ.value = '';
            if (searchMajor) searchMajor.value = '';
            render();
        });
    }

    if (searchQ) {
        searchQ.addEventListener('keyup', function (e) {
            if (e.keyCode === 13) {
                state.q = searchQ.value.trim();
                state.page = 1;
                render();
            }
        });
    }

    if (perPageEl) {
        perPageEl.addEventListener('change', function () {
            state.per_page = parseInt(perPageEl.value, 10) || 20;
            state.page = 1;
            render();
        });
    }

    function gotoPage() {
        if (!gotoEl) return;
        var page = parseInt(gotoEl.value, 10);
        if (isNaN(page)) return;
        var max = parseInt(gotoEl.max, 10) || 1;
        if (page < 1) page = 1;
        if (page > max) page = max;
        if (page !== state.page) {
            state.page = page;
            render();
        }
    }

    var btnGoto = document.getElementById('btn_goto');
    if (btnGoto) btnGoto.addEventListener('click', gotoPage);
    if (gotoEl) {
        gotoEl.addEventListener('keyup', function (e) {
            if (e.keyCode === 13) gotoPage();
        });
    }

    /* ---------- 新增 / 编辑弹窗 ---------- */
    var editModal = document.getElementById('edit_modal');
    var editForm = document.getElementById('edit_form');
    var editSave = document.getElementById('edit_save');
    var editModalTitle = document.getElementById('edit_modal_title');
    var currentEditId = null;
    var editMode = 'edit';
    var EDIT_FIELDS = ['name', 'issue_date', 'major', 'level_range', 'level', 'org',
        'id_card', 'nationality', 'ethnicity', 'birth_date', 'name_pinyin', 'cert_no'];

    function showModal() {
        if (editModal) editModal.style.display = 'flex';
    }

    function openNewModal() {
        editMode = 'new';
        currentEditId = null;
        if (editModalTitle) editModalTitle.textContent = '新增证书';
        EDIT_FIELDS.forEach(function (f) {
            var input = editForm.elements[f];
            if (input) input.value = '';
        });
        showModal();
    }

    function openEditModal(id) {
        fetch('/admin/api/certificate/' + id, { credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 401) { window.location = '/admin/login'; throw new Error('unauthorized'); }
                return r.json();
            })
            .then(function (res) {
                if (!res.success) { alert(res.message || '加载失败'); return; }
                editMode = 'edit';
                currentEditId = id;
                if (editModalTitle) editModalTitle.textContent = '编辑证书';
                EDIT_FIELDS.forEach(function (f) {
                    var input = editForm.elements[f];
                    if (input) input.value = (res.data[f] === null || res.data[f] === undefined) ? '' : res.data[f];
                });
                showModal();
            })
            .catch(function () { alert('加载失败，请重试'); });
    }

    function closeEditModal() {
        if (editModal) editModal.style.display = 'none';
        currentEditId = null;
    }

    function saveEdit() {
        var payload = {};
        EDIT_FIELDS.forEach(function (f) {
            var input = editForm.elements[f];
            payload[f] = input ? input.value.trim() : '';
        });
        var url = editMode === 'new'
            ? '/admin/api/certificate'
            : '/admin/api/certificate/' + currentEditId;

        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.success) {
                    closeEditModal();
                    render();
                } else {
                    alert(res.message || '保存失败');
                }
            })
            .catch(function () { alert('保存失败，请重试'); });
    }

    var btnNew = document.getElementById('btn_new');
    if (btnNew) btnNew.addEventListener('click', openNewModal);

    var editClose = document.getElementById('edit_modal_close');
    var editCancel = document.getElementById('edit_cancel');
    if (editClose) editClose.addEventListener('click', closeEditModal);
    if (editCancel) editCancel.addEventListener('click', closeEditModal);
    if (editSave) editSave.addEventListener('click', saveEdit);
    if (editModal) {
        editModal.addEventListener('click', function (e) {
            if (e.target === editModal) closeEditModal();
        });
    }

    /* ---------- 导入弹窗 ---------- */
    var importModal = document.getElementById('import_modal');
    var importFile = document.getElementById('import_file');
    var importResult = document.getElementById('import_result');
    var btnDoImport = document.getElementById('btn_do_import');

    function escapeText(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/[&<>"]/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
            });
    }

    function openImportModal() {
        if (importResult) importResult.innerHTML = '';
        if (importFile) importFile.value = '';
        if (importModal) importModal.style.display = 'flex';
    }

    function closeImportModal() {
        if (importModal) importModal.style.display = 'none';
    }

    function renderImportResult(res) {
        if (!importResult) return;
        if (!res.success) {
            importResult.innerHTML = '<div class="import-msg import-msg-error">' +
                escapeText(res.message || '导入失败') + '</div>';
            return;
        }
        var data = res.data || {};
        var html = '<div class="import-msg">' + escapeText(res.message || '') + '</div>';
        html += '<div class="import-table-wrap">' +
            '<table class="data-table"><thead><tr>' +
            '<th>行号</th><th>姓名</th><th>证书编号</th><th>结果</th><th>说明</th>' +
            '</tr></thead><tbody>';
        (data.items || []).forEach(function (it) {
            html += '<tr class="' + (it.ok ? '' : 'row-fail') + '">' +
                '<td>' + escapeText(it.row) + '</td>' +
                '<td>' + escapeText(it.name) + '</td>' +
                '<td>' + escapeText(it.cert_no) + '</td>' +
                '<td>' + (it.ok ? '<span class="tag tag-ok">成功</span>'
                    : '<span class="tag tag-fail">失败</span>') + '</td>' +
                '<td>' + escapeText(it.message) + '</td></tr>';
        });
        html += '</tbody></table></div>';
        importResult.innerHTML = html;
    }

    function doImport() {
        if (!importFile || !importFile.files || !importFile.files[0]) {
            alert('请选择要导入的 Excel 文件');
            return;
        }
        var fd = new FormData();
        fd.append('file', importFile.files[0]);
        if (btnDoImport) btnDoImport.disabled = true;
        fetch('/admin/certificates/import', {
            method: 'POST',
            credentials: 'same-origin',
            body: fd
        })
            .then(function (r) {
                if (r.status === 401) { window.location = '/admin/login'; throw new Error('unauthorized'); }
                return r.json();
            })
            .then(function (res) {
                renderImportResult(res);
                if (res.success) render();
            })
            .catch(function () { renderImportResult({ success: false, message: '导入失败，请重试' }); })
            .finally(function () { if (btnDoImport) btnDoImport.disabled = false; });
    }

    var btnImport = document.getElementById('btn_import');
    if (btnImport) btnImport.addEventListener('click', openImportModal);
    var importClose = document.getElementById('import_modal_close');
    if (importClose) importClose.addEventListener('click', closeImportModal);
    if (btnDoImport) btnDoImport.addEventListener('click', doImport);
    if (importModal) {
        importModal.addEventListener('click', function (e) {
            if (e.target === importModal) closeImportModal();
        });
    }

    render();
})();
