using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Models;
using System.Collections.Generic;
using System.Linq;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class CamerasController : Controller
    {
        // TEMP storage (replace with DB later)
        private static List<Camera> cameras = new List<Camera>();

        // ===============================
        // MAIN PAGE (GRID + FOCUS VIEW)
        // ===============================
        public IActionResult Index()
        {
            return View(cameras);
        }

        // ===============================
        // ADD CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(Camera camera)
        {
            if (!ModelState.IsValid)
            {
                return View("Index", cameras);
            }

            // Prevent duplicate names
            if (cameras.Any(c => c.Name == camera.Name))
            {
                ModelState.AddModelError("", "Camera name already exists.");
                return View("Index", cameras);
            }

            cameras.Add(camera);

            return RedirectToAction("Index");
        }

        // ===============================
        // DELETE CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Delete(string name)
        {
            var cam = cameras.FirstOrDefault(c => c.Name == name);

            if (cam != null)
            {
                cameras.Remove(cam);
            }

            return RedirectToAction("Index");
        }
    }
}