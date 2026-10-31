/* 后台机构管理：机构列表 + 生成报名链接/二维码 */
(function () {
    'use strict';

    var tbody = document.getElementById('inst_tbody');
    var totalEl = document.getElementById('total');
    var nameInput = document.getElementById('new_name');
    var expiresInput = document.getElementById('new_expires');

    // 默认有效期 6 个月
    function defaultExpiry() {
        var d = new Date();
        d.setMonth(d.getMonth() + 6);
        var m = ('0' + (d.getMonth() + 1)).slice(-2);
        var day = ('0' + d.getDate()).slice(-2);
        return d.getFullYear() + '-' + m + '-' + day;
    }
    if (expiresInput) expiresInput.value = defaultExpiry();

    function escapeText(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/[&<>"]/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
            });
    }

    function td(text, cls) {
        var el = document.createElement('td');
        if (cls) el.className = cls;
        el.textContent = (text === null || text === undefined) ? '' : text;
        return el;
    }

    function render() {
        return fetch('/new/manage/api/institutions?page=1&per_page=200', { credentials: 'same-origin' })
            .then(function (r) {
                if (r.status === 401) { window.location = '/new/manage/login'; throw new Error('unauthorized'); }
                return r.json();
            })
            .then(function (res) {
                tbody.innerHTML = '';
                var list = res.data || [];
                if (totalEl) totalEl.textContent = res.pagination ? res.pagination.total : list.length;
                if (!list.length) {
                    var tr = document.createElement('tr');
                    var cell = document.createElement('td');
                    cell.colSpan = 8;
                    cell.className = 'empty';
                    cell.textContent = '暂无机构，请在上方输入名称生成报名链接';
                    tr.appendChild(cell);
                    tbody.appendChild(tr);
                    return;
                }
                list.forEach(function (item) {
                    var row = document.createElement('tr');
                    row.appendChild(td(item.name));
                    row.appendChild(td(item.account));
                    row.appendChild(td(item.password));

                    var expTd = document.createElement('td');
                    if (item.expires_at) {
                        expTd.textContent = item.expires_at;
                        if (item.expired) {
                            var warn = document.createElement('span');
                            warn.className = 'tag tag-fail';
                            warn.textContent = '已过期';
                            warn.style.marginLeft = '6px';
                            expTd.appendChild(warn);
                        }
                    } else {
                        expTd.textContent = '长期';
                    }
                    row.appendChild(expTd);

                    var linkTd = document.createElement('td');
                    var a = document.createElement('a');
                    a.href = item.link;
                    a.target = '_blank';
                    a.rel = 'noopener';
                    a.textContent = item.link;
                    a.style.color = '#d8010f';
                    a.style.wordBreak = 'break-all';
                    linkTd.appendChild(a);
                    row.appendChild(linkTd);

                    row.appendChild(td(String(item.count)));
                    row.appendChild(td(item.created_at));

                    var op = document.createElement('td');
                    op.className = 'op nowrap';
                    op.appendChild(button('编辑', function () { openEdit(item); }));
                    op.appendChild(button('链接二维码', function () { openQr(item); }));
                    op.appendChild(button('复制链接', function () { copyText(item.link); }));
                    op.appendChild(button('删除', function () { doDelete(item.id); }, true));
                    row.appendChild(op);

                    tbody.appendChild(row);
                });
            })
            .catch(function () {});
    }

    function button(text, handler, danger) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'link-btn' + (danger ? ' danger' : '');
        b.textContent = text;
        b.addEventListener('click', handler);
        return b;
    }

    function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () { alert('链接已复制'); },
                function () { fallbackCopy(text); });
        } else { fallbackCopy(text); }
    }
    function fallbackCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); alert('链接已复制'); }
        catch (e) { alert('复制失败，请手动复制'); }
        ta.remove();
    }

    function doDelete(id) {
        if (!window.confirm('确定删除该机构吗？（已报名数据仍会保留机构名称）')) return;
        fetch('/new/manage/institution/' + id + '/delete', { method: 'POST', credentials: 'same-origin' })
            .then(function () { render(); })
            .catch(function () { alert('操作失败，请重试'); });
    }

    /* ---------- 二维码弹窗 ---------- */
    var qrModal = document.getElementById('qr_modal');
    var qrImg = document.getElementById('qr_img');
    var qrUrl = document.getElementById('qr_url');
    var qrLoading = document.getElementById('qr_loading');
    var qrTitle = document.getElementById('qr_title');
    var qrAccount = document.getElementById('qr_account');
    var qrPassword = document.getElementById('qr_password');
    var currentImage = '';

    function openQr(item) {
        if (qrTitle) qrTitle.textContent = item.name + ' · 报名二维码';
        if (qrAccount) qrAccount.textContent = item.account || '—';
        if (qrPassword) qrPassword.textContent = item.password || '—';
        currentImage = '';
        if (qrImg) qrImg.removeAttribute('src');
        if (qrUrl) qrUrl.value = item.link;
        if (qrLoading) qrLoading.style.display = 'block';
        if (qrModal) qrModal.style.display = 'flex';
        fetch('/new/manage/api/institution/' + item.id + '/qrcode', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (qrLoading) qrLoading.style.display = 'none';
                if (!res.success) { alert(res.message || '生成二维码失败'); return; }
                currentImage = res.data.image || '';
                if (qrImg) qrImg.src = currentImage;
                if (qrUrl) qrUrl.value = res.data.url || item.link;
            })
            .catch(function () { if (qrLoading) qrLoading.style.display = 'none'; alert('生成二维码失败'); });
    }
    function closeQr() { if (qrModal) qrModal.style.display = 'none'; }

    var qrClose = document.getElementById('qr_modal_close');
    if (qrClose) qrClose.addEventListener('click', closeQr);
    if (qrModal) qrModal.addEventListener('click', function (e) { if (e.target === qrModal) closeQr(); });
    var qrCopyLink = document.getElementById('qr_copy_link');
    if (qrCopyLink) qrCopyLink.addEventListener('click', function () { if (qrUrl) copyText(qrUrl.value); });
    var qrCopyImg = document.getElementById('qr_copy_img');
    if (qrCopyImg) qrCopyImg.addEventListener('click', function () {
        if (!currentImage) { alert('二维码尚未生成'); return; }
        if (navigator.clipboard && window.ClipboardItem) {
            fetch(currentImage).then(function (r) { return r.blob(); })
                .then(function (blob) { return navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]); })
                .then(function () { alert('二维码已复制'); })
                .catch(function () { copyImageFallback(currentImage); });
        } else {
            copyImageFallback(currentImage);
        }
    });

    // HTTP 下 navigator.clipboard 不可用时的兜底：选区 + execCommand('copy')
    function copyImageFallback(dataUrl) {
        try {
            var box = document.createElement('div');
            box.setAttribute('contenteditable', 'true');
            box.style.position = 'fixed';
            box.style.left = '-9999px';
            box.style.top = '0';
            var img = document.createElement('img');
            img.src = dataUrl;
            box.appendChild(img);
            document.body.appendChild(box);
            var range = document.createRange();
            range.selectNodeContents(box);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            var ok = document.execCommand('copy');
            sel.removeAllRanges();
            box.remove();
            if (ok) { alert('二维码已复制'); } else { downloadImg(); }
        } catch (e) { downloadImg(); }
    }
    function downloadImg() {
        var a = document.createElement('a');
        a.href = currentImage;
        a.download = '报名二维码.png';
        document.body.appendChild(a); a.click(); a.remove();
    }

    /* ---------- 编辑机构 ---------- */
    var editModal = document.getElementById('edit_modal');
    var editForm = document.getElementById('edit_form');
    var editId = null;

    function openEdit(item) {
        editId = item.id;
        if (!editForm) return;
        editForm.elements['name'].value = item.name || '';
        editForm.elements['expires_at'].value = item.expires_at || '';
        editForm.elements['account'].value = item.account || '—';
        editForm.elements['password'].value = item.password || '—';
        if (editModal) editModal.style.display = 'flex';
    }
    function closeEdit() { if (editModal) editModal.style.display = 'none'; editId = null; }

    function saveEdit() {
        if (!editForm || editId === null) return;
        var name = editForm.elements['name'].value.trim();
        if (!name) { alert('请填写机构名称'); return; }
        fetch('/new/manage/api/institution/' + editId, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, expires_at: editForm.elements['expires_at'].value })
        })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.success) { closeEdit(); render(); }
                else { alert(res.message || '保存失败'); }
            })
            .catch(function () { alert('保存失败，请重试'); });
    }

    var eClose = document.getElementById('edit_modal_close');
    var eCancel = document.getElementById('edit_cancel');
    var eSave = document.getElementById('edit_save');
    if (eClose) eClose.addEventListener('click', closeEdit);
    if (eCancel) eCancel.addEventListener('click', closeEdit);
    if (eSave) eSave.addEventListener('click', saveEdit);
    if (editModal) editModal.addEventListener('click', function (e) { if (e.target === editModal) closeEdit(); });

    /* ---------- 新增 ---------- */
    var btnCreate = document.getElementById('btn_create');
    if (btnCreate) btnCreate.addEventListener('click', function () {
        var name = nameInput ? nameInput.value.trim() : '';
        if (!name) { alert('请填写机构名称'); return; }
        btnCreate.disabled = true;
        fetch('/new/manage/api/institution', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                expires_at: expiresInput ? expiresInput.value : ''
            })
        })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                btnCreate.disabled = false;
                if (res.success) {
                    if (nameInput) nameInput.value = '';
                    if (expiresInput) expiresInput.value = defaultExpiry();
                    render();
                    openQr(res.data);
                } else {
                    alert(res.message || '创建失败');
                }
            })
            .catch(function () { btnCreate.disabled = false; alert('创建失败，请重试'); });
    });

    render();
})();
