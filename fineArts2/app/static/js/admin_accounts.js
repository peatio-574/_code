/* 后台账号管理（仅超管）：账号、密码、角色、所属机构；支持编辑/删除 */
(function () {
    'use strict';

    var tbody = document.getElementById('acc_tbody');
    var totalEl = document.getElementById('total');
    var searchQ = document.getElementById('search_q');
    var searchInstitution = document.getElementById('search_institution');
    var state = { page: 1, per_page: 100, q: '', institution: '' };

    var modal = document.getElementById('acc_modal');
    var form = document.getElementById('acc_form');
    var editId = null;
    var currentAccount = null;

    function td(text, cls) {
        var el = document.createElement('td');
        if (cls) el.className = cls;
        el.textContent = (text === null || text === undefined || text === '') ? '—' : text;
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

    function actionCell(item) {
        var cell = document.createElement('td');
        cell.className = 'op nowrap';
        cell.appendChild(linkBtn('编辑', function () { openEdit(item); }));
        cell.appendChild(linkBtn('删除', function () { doDelete(item); }, true));
        return cell;
    }

    function render() {
        var qs = 'page=' + state.page + '&per_page=' + state.per_page + '&q=' + encodeURIComponent(state.q);
        if (state.institution === '__none__') {
            qs += '&no_institution=1';
        } else if (state.institution) {
            qs += '&institution_id=' + encodeURIComponent(state.institution);
        }
        return fetch('/new/manager/api/accounts?' + qs, { credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 401) { window.location = '/new/manager/login'; throw new Error('unauthorized'); }
                return r.json();
            })
            .then(function (res) {
                tbody.innerHTML = '';
                if (!res.success) {
                    var tr0 = document.createElement('tr');
                    var c0 = document.createElement('td');
                    c0.colSpan = 6; c0.className = 'empty'; c0.textContent = res.message || '加载失败';
                    tr0.appendChild(c0); tbody.appendChild(tr0);
                    return;
                }
                var list = res.data || [];
                if (totalEl) totalEl.textContent = res.pagination ? res.pagination.total : list.length;
                if (!list.length) {
                    var tr = document.createElement('tr');
                    var cell = document.createElement('td');
                    cell.colSpan = 6; cell.className = 'empty'; cell.textContent = '暂无账号';
                    tr.appendChild(cell); tbody.appendChild(tr);
                    return;
                }
                list.forEach(function (item) {
                    var row = document.createElement('tr');
                    row.appendChild(td(item.username));
                    row.appendChild(td(item.password));
                    row.appendChild(td(item.role_text));
                    row.appendChild(td(item.institution));
                    row.appendChild(td(item.created_at));
                    row.appendChild(actionCell(item));
                    tbody.appendChild(row);
                });
            })
            .catch(function () {});
    }

    function openEdit(item) {
        currentAccount = item;
        editId = item.id;
        if (!form) return;
        form.elements['username'].value = item.username || '';
        form.elements['password'].value = '';
        form.elements['role'].value = item.role || 'admin';
        if (modal) modal.style.display = 'flex';
    }
    function closeEdit() { if (modal) modal.style.display = 'none'; editId = null; currentAccount = null; }

    function saveEdit() {
        if (!form || editId === null) return;
        var payload = {
            username: form.elements['username'].value.trim(),
            password: form.elements['password'].value.trim(),
            role: form.elements['role'].value,
        };
        if (!payload.username) { alert('请填写账号'); return; }
        fetch('/new/manager/api/account/' + editId, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.success) { closeEdit(); render(); }
                else { alert(res.message || '保存失败'); }
            })
            .catch(function () { alert('保存失败，请重试'); });
    }

    function doDelete(item) {
        if (!window.confirm('确定删除账号「' + item.username + '」吗？')) return;
        fetch('/new/manager/api/account/' + item.id + '/delete', { method: 'POST', credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.success) { render(); }
                else { alert(res.message || '删除失败'); }
            })
            .catch(function () { alert('删除失败，请重试'); });
    }

    var btnSearch = document.getElementById('btn_search');
    if (btnSearch) btnSearch.addEventListener('click', function () {
        state.q = searchQ ? searchQ.value.trim() : '';
        state.institution = searchInstitution ? searchInstitution.value : '';
        render();
    });
    var btnReset = document.getElementById('btn_reset');
    if (btnReset) btnReset.addEventListener('click', function () {
        state.q = ''; state.institution = '';
        if (searchQ) searchQ.value = '';
        if (searchInstitution) searchInstitution.value = '';
        render();
    });

    var mClose = document.getElementById('acc_modal_close');
    var mCancel = document.getElementById('acc_cancel');
    var mSave = document.getElementById('acc_save');
    if (mClose) mClose.addEventListener('click', closeEdit);
    if (mCancel) mCancel.addEventListener('click', closeEdit);
    if (mSave) mSave.addEventListener('click', saveEdit);
    if (modal) modal.addEventListener('click', function (e) { if (e.target === modal) closeEdit(); });

    // 加载机构下拉
    function loadInstitutions() {
        if (!searchInstitution) return;
        fetch('/new/manager/api/account-institutions', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (!res.success) return;
                (res.data || []).forEach(function (inst) {
                    var opt = document.createElement('option');
                    opt.value = String(inst.id);
                    opt.textContent = inst.name;
                    searchInstitution.appendChild(opt);
                });
            })
            .catch(function () {});
    }

    loadInstitutions();
    render();
})();
