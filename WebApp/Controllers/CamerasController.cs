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
        // TEMP storage
        private static List<Camera> cameras = new List<Camera>();
        private static int nextId = 1;

        // ===============================
        // MAIN PAGE
        // ===============================
        public IActionResult Index()
        {
            // DEFAULT CAMERA (only once)
            if (!cameras.Any())
            {
                cameras.Add(new Camera
                {
                    Id = nextId++,
                    Name = "Main Entrance",
                    Location = "Front Gate",
                    IpAddress = "192.168.1.10",
                    Port = 554
                });
            }

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

            camera.Id = nextId++;
            cameras.Add(camera);

            return RedirectToAction("Index");
        }

        // ===============================
        // EDIT CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Edit(Camera camera)
        {
            var existing = cameras.FirstOrDefault(c => c.Id == camera.Id);

            if (existing == null)
            {
                return RedirectToAction("Index");
            }

            // Prevent duplicate name (except itself)
            if (cameras.Any(c => c.Name == camera.Name && c.Id != camera.Id))
            {
                ModelState.AddModelError("", "Camera name already exists.");
                return View("Index", cameras);
            }

            existing.Name = camera.Name;
            existing.Location = camera.Location;
            existing.IpAddress = camera.IpAddress;
            existing.Port = camera.Port;

            return RedirectToAction("Index");
        }

        // ===============================
        // DELETE CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Delete(int id)
        {
            var cam = cameras.FirstOrDefault(c => c.Id == id);

            if (cam != null)
            {
                cameras.Remove(cam);
            }

            return RedirectToAction("Index");
        }
    }
}