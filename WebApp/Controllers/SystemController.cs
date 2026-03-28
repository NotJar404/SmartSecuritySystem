using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Services;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin")] // 🔥 ONLY ADMIN CAN ACCESS
    public class SystemController : Controller
    {
        private readonly SystemService _systemService;

        public SystemController(SystemService systemService)
        {
            _systemService = systemService;
        }

        public IActionResult Index()
        {
            var model = _systemService.GetSystemStatus();
            return View(model);
        }

        [HttpPost]
        public IActionResult UpdateSetting(string setting, bool value)
        {
            _systemService.UpdateSetting(setting, value);
            return Json(new { success = true });
        }
    }
}