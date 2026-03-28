using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Models;
using System.Collections.Generic;
using System.Linq;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")] // 🔥 USE THIS INSTEAD OF SESSION
    public class CamerasController : Controller
    {
        // TEMP: in-memory camera list (replace with DB later)
        private static List<Camera> cameras = new List<Camera>();

        // Camera management page (Add / List)
        public IActionResult Index()
        {
            return View(cameras);
        }

        // Live Monitoring page (all cameras)
        public IActionResult Live(string selectedCamera = null)
        {
            Camera activeCam = null;

            // If user selected a camera
            if (!string.IsNullOrEmpty(selectedCamera))
            {
                activeCam = cameras.FirstOrDefault(c => c.Name == selectedCamera);
            }

            // Default to first camera
            if (activeCam == null && cameras.Count > 0)
            {
                activeCam = cameras[0];
            }

            ViewBag.ActiveCamera = activeCam;

            return View(cameras);
        }

        // Add a new camera
        [HttpPost]
        public IActionResult Add(Camera camera)
        {
            if (ModelState.IsValid)
            {
                if (!cameras.Exists(c => c.Name == camera.Name))
                {
                    cameras.Add(camera);
                }
            }

            return RedirectToAction("Index");
        }

        // Delete a camera
        [HttpPost]
        public IActionResult Delete(string name)
        {
            var cam = cameras.Find(c => c.Name == name);

            if (cam != null)
            {
                cameras.Remove(cam);
            }

            return Redirect(Request.Headers["Referer"].ToString());
        }

        // View single camera
        public IActionResult ViewCamera(string name)
        {
            var cam = cameras.Find(c => c.Name == name);

            if (cam == null)
                return RedirectToAction("Index");

            return View(cam);
        }
    }
}