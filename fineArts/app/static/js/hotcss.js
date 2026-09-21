(function main() {
    rem();
    window.addEventListener('resize', function () {
        rem()
    })
})()
function rem() {
    var cw =
        window.innerWidth ||
        document.documentElement.clientWidth ||
        document.body.clientWidth;
    if (cw > 1920) {
        cw = 1920;
    } else if (cw < 769) {
        document.getElementsByTagName('html')[0].style.fontSize =
            20 * (cw / 375) + 'px';
    }
}