/* 前台查询页：固定 HTML + JSON 接口填充 */
(function () {
    'use strict';

    var typeInput = document.getElementById('query_type');
    var idNum = document.getElementById('id_num');
    var certCode = document.getElementById('certificate_code');
    var radioButtons = document.querySelectorAll('.radio-button');

    var formErrorEl = document.getElementById('form_error');
    var result = document.getElementById('result');
    var multiTable = document.getElementById('multi_table');
    var multiBody = document.getElementById('multi_body');

    /* ---------- 查询类型切换 ---------- */
    function switchType(type) {
        if (typeInput) typeInput.value = type;
        radioButtons.forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-type') === type);
        });
        if (type === '2') {
            if (idNum) { idNum.classList.add('hidden'); idNum.value = ''; }
            if (certCode) certCode.classList.remove('hidden');
        } else {
            if (certCode) { certCode.classList.add('hidden'); certCode.value = ''; }
            if (idNum) idNum.classList.remove('hidden');
        }
    }

    radioButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            switchType(btn.getAttribute('data-type'));
        });
    });

    /* ---------- 验证码 ---------- */
    var captchaImg = document.getElementById('captcha_img');
    var captchaKey = document.getElementById('captcha_key');
    var captchaChange = document.getElementById('captcha_change');
    var captchaValue = document.getElementById('captcha_value');

    function refreshCaptcha() {
        fetch('/captcha/new', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res && res.code === 200) {
                    if (captchaImg) captchaImg.src = res.data.img;
                    if (captchaKey) captchaKey.value = res.data.key;
                    if (captchaValue) captchaValue.value = '';
                }
            })
            .catch(function () { /* 忽略 */ });
    }

    if (captchaImg) captchaImg.addEventListener('click', refreshCaptcha);
    if (captchaChange) captchaChange.addEventListener('click', refreshCaptcha);

    /* ---------- 结果填充（固定 HTML） ---------- */
    function clearResult() {
        if (result) result.style.display = 'none';
        if (singleCard) singleCard.style.display = 'none';
        if (multiTable) multiTable.style.display = 'none';
        if (multiBody) multiBody.innerHTML = '';
    }

    /* 表单内联提示（显示在「证书编号」文案后面） */
    function showFormError(message) {
        if (formErrorEl) formErrorEl.textContent = message || '';
    }

    function clearFormError() {
        if (formErrorEl) formErrorEl.textContent = '';
    }

    function fillMulti(list) {
        multiBody.innerHTML = '';
        list.forEach(function (cert) {
            var tr = document.createElement('tr');
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', function () { window.location = cert.detail_url; });

            var tdDate = document.createElement('td');
            tdDate.textContent = cert.issue_date || '';
            var tdCertNo = document.createElement('td');
            tdCertNo.textContent = cert.cert_no || '';
            var tdMajor = document.createElement('td');
            tdMajor.textContent = (cert.major || '') + (cert.level || '') + '级';
            var tdOp = document.createElement('td');
            tdOp.className = 'op';
            var a = document.createElement('a');
            a.className = 'link-view';
            a.href = cert.detail_url;
            a.textContent = '查看';
            tdOp.appendChild(a);

            tr.appendChild(tdDate);
            tr.appendChild(tdCertNo);
            tr.appendChild(tdMajor);
            tr.appendChild(tdOp);
            multiBody.appendChild(tr);
        });
        multiTable.style.display = 'table';
    }

    function renderData(list) {
        if (notify) notify.innerHTML = '';
        if (!list || list.length === 0) {
            var type = typeInput ? typeInput.value : '1';
            showFormError(type === '2' ? '证书编号错误' : '证件号错误');
            if (result) result.style.display = 'none';
            return;
        }
        clearFormError();
        fillMulti(list);
        result.style.display = 'block';
    }

    var clearBtn = document.getElementById('clear_result');
    if (clearBtn) clearBtn.addEventListener('click', clearResult);

    /* ---------- 提交查询 ---------- */
    function doQuery() {
        var name = document.getElementById('student_name');
        var type = typeInput ? typeInput.value : '1';

        if (name && !name.value.trim()) { showFormError('请输入姓名'); name.focus(); return; }
        if (type === '2') {
            if (certCode && !certCode.value.trim()) { showFormError('请输入证书编号'); certCode.focus(); return; }
        } else if (idNum && !idNum.value.trim()) { showFormError('请输入证件号'); idNum.focus(); return; }
        if (captchaValue && !captchaValue.value.trim()) { showFormError('请输入验证码'); captchaValue.focus(); return; }
        clearFormError();

        var payload = {
            student_name: name ? name.value.trim() : '',
            type: type,
            id_num: idNum ? idNum.value.trim() : '',
            certificate_code: certCode ? certCode.value.trim() : '',
            captcha_key: captchaKey ? captchaKey.value : '',
            captcha_value: captchaValue ? captchaValue.value.trim() : ''
        };

        return fetch('/query', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.success) {
                    renderData(res.data || []);
                } else {
                    showFormError(res.message || '查询失败');
                }
                // 验证码为一次性，查询后统一刷新，避免下次查询误报「验证码错误」
                refreshCaptcha();
            })
            .catch(function () {
                showFormError('网络错误，请稍后重试');
                refreshCaptcha();
            });
    }

    var btn = document.getElementById('btn_query');
    if (btn) btn.addEventListener('click', doQuery);

    // 支持回车查询
    document.querySelectorAll('#queryForm .form-input').forEach(function (input) {
        input.addEventListener('keyup', function (e) {
            if (e.keyCode === 13) doQuery();
        });
    });
})();
